"""Three vantages, overlapping windows: what the capture is allowed to conclude.

The WSL symptom - `127.0.0.1:<published port>` refusing a connection for the whole 30s bound - has
stayed undetermined because every observation of it was taken from one side. One refusal cannot
tell a database that never came up from a port that was never published from a port published
somewhere this side cannot reach.

These checks are about the narrowing, not about diagnosing that symptom: it has not been reproduced
and is not claimed to be solved here. Two of the boundaries below were real defects in the first
submission - a probe that could not run was counted as a service refusing, and an answer arriving
after the deadline edited a record that had already been handed back.
"""
from __future__ import annotations

import os
import socket
import threading
import time

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
    (True, True, True, "all_reachable"),     # nothing was refusing during these windows
])
def test_the_verdict_names_the_segment_the_three_answers_point_at(container, windows, wsl, verdict):
    assert port_diagnosis.narrow(answers(container, windows, wsl)) == verdict
    assert port_diagnosis.NARROWINGS[verdict]


@pytest.mark.parametrize("container,windows,wsl", [
    (None, True, True),      # the container could not be asked
    (True, None, False),     # Windows could not be asked, so "WSL only" is not established
    (True, True, None),      # WSL could not be asked
    (None, None, None),
    # The three the first submission got wrong: it read each of these as a decided verdict, because
    # it checked "container is False" before checking whether the other two had answered at all.
    (False, None, True),     # was read as "service"
    (True, False, None),     # was read as "publication"
    (None, True, False),     # was read as "wsl_path"
])
def test_a_vantage_that_could_not_be_asked_never_becomes_a_verdict(container, windows, wsl):
    """Not asking is not the same as being refused, and it must not narrow anything."""
    assert port_diagnosis.narrow(answers(container, windows, wsl)) == "undetermined"


def prints(monkeypatch, out, code):
    """Make the probe command run and print exactly this. Running is the point: a command that
    could not start was already handled; a command that ran and failed was not."""
    import subprocess

    def fake(argv, **kwargs):
        return subprocess.CompletedProcess(argv, code, out, "")

    monkeypatch.setattr(subprocess, "run", fake)


def test_a_docker_exec_that_ran_and_failed_is_not_a_database_that_refused(monkeypatch):
    """The defect this bites: a non-zero exit was recorded as `reachable=False`, which is "service".

    A container that is gone, a daemon that is not answering and a missing client all end here with
    a non-zero exit and a message from docker. None of them is evidence about the database.
    """
    prints(monkeypatch, "Error response from daemon: No such container: deadbeef", 1)

    record = port_diagnosis._tcp_in_container("deadbeef", "postgres", 1.0)

    assert record["reachable"] is None, "nothing was observed, so there is nothing to be false"
    assert record["observed"] is False
    assert record["why"] in port_diagnosis.NOT_OBSERVED
    assert port_diagnosis.narrow(answers(record["reachable"], True, True)) == "undetermined"


def test_a_reply_this_code_does_not_recognise_is_not_an_answer_and_is_not_quoted(monkeypatch):
    """An unexpected reply observes nothing - and its text never reaches the record.

    The old capture copied up to 80 characters of whatever the command printed into the artifact,
    which is exactly where a connection string or a password would end up if one ever appeared in
    an error message.
    """
    prints(monkeypatch, "FATAL: password authentication failed for user zeus_probe", 0)

    record = port_diagnosis._tcp_in_container("deadbeef", "postgres", 1.0)

    assert "password" not in str(record) and "zeus_probe" not in str(record)
    assert record["reachable"] is None and record["observed"] is False
    assert record["why"] == "unrecognised_reply"


@pytest.mark.parametrize("reply,reachable,code", [
    ("127.0.0.1:5432 - accepting connections", True, 1),
    ("127.0.0.1:5432 - rejecting connections", False, 0),
    ("127.0.0.1:5432 - no response", False, 0),
])
def test_the_replies_pg_isready_documents_are_the_only_ones_read_as_answers(monkeypatch, reply,
                                                                           reachable, code):
    """The exit code disagrees with the reply here on purpose.

    The old capture read `returncode == 0` and nothing else, so every one of these came out
    inverted. What is read now is the sentence pg_isready is documented to print.
    """
    prints(monkeypatch, reply, code)

    record = port_diagnosis._tcp_in_container("deadbeef", "postgres", 1.0)
    assert record["reachable"] is reachable
    assert record["observed"] is True


def test_a_probe_that_prints_something_else_observes_nothing(monkeypatch):
    """`open` and `shut` are the two words the local probes were told to print. Nothing else counts.

    The defect this bites: anything that did not end in "open" was read as the port being shut, so
    `wsl.exe` refusing to start became "WSL cannot reach the port" - a verdict about a route that
    was never tested.
    """
    prints(monkeypatch, "wsl.exe: The Windows Subsystem for Linux is not installed.", 1)

    away = port_diagnosis._tcp_from_wsl if os.name == "nt" else port_diagnosis._tcp_from_windows
    record = away(59992, 1.0)

    assert record["reachable"] is None, "the route was never tested, so it did not fail"
    assert port_diagnosis.narrow(answers(True, True, record["reachable"])) == "undetermined"
    assert record["observed"] is False and record["why"] == "command_failed"


def test_a_port_that_is_open_here_is_reported_reachable_from_this_side():
    """The vantage that is this process is a real socket, not a description of one."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        record = port_diagnosis._tcp_here(port, 2.0)
        assert record["reachable"] is True and record["observed"] is True
        assert record["seconds"] >= 0
    finally:
        listener.close()

    shut = port_diagnosis._tcp_here(port, 0.5)
    assert shut["reachable"] is False and shut["observed"] is True and shut["error"]


def test_every_vantage_answers_or_says_it_was_not_asked():
    """A capture always has all three entries, so a missing one can never be read as a pass."""
    record = port_diagnosis.observe(59998, service="postgres", container=None, seconds=8)

    assert set(record["observations"]) == set(port_diagnosis.VANTAGES)
    for name, observation in record["observations"].items():
        assert "reachable" in observation and "observed" in observation, name
        assert "looked_from" in observation and "looked_until" in observation, name
    container = record["observations"]["container"]
    assert container["observed"] is False and container["why"] == "no_container"
    assert record["verdict"] == "undetermined", "the container was never asked"
    assert record["context"]["platform"] and "seconds" in record


def test_the_container_vantage_says_which_port_it_asked_about():
    """It asks the service's own port, which is not the published number, and the record says so."""
    record = port_diagnosis._tcp_in_container("", "postgres", 1.0)
    assert record["observed"] is False and record["asked_port"] == "5432"

    this_host = port_diagnosis.observe(59997, service="redis", container=None, seconds=8)
    assert this_host["observations"]["container"]["reachable"] is None
    assert this_host["observations"]["container"]["asked_port"] == "6379"


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


def test_an_answer_that_arrives_late_cannot_edit_the_record_that_was_handed_back(monkeypatch):
    """The defect this bites: a probe finishing after the deadline rewrote a returned verdict.

    The slow vantage is made to answer `open` well after the budget. The record that came back must
    still say that vantage observed nothing, must still be undetermined, and must still say so a
    second later, when the late worker has written its answer somewhere that is not this record.
    """
    released = threading.Event()

    def slow(port, seconds):
        released.wait(5.0)
        return {"reachable": True, "observed": True, "how": "slow probe"}

    monkeypatch.setattr(port_diagnosis, "_tcp_from_wsl", slow)
    monkeypatch.setattr(port_diagnosis, "_tcp_from_windows",
                        lambda port, seconds: {"reachable": True, "observed": True, "how": "stub"})
    monkeypatch.setattr(port_diagnosis, "_tcp_in_container",
                        lambda container, service, seconds: {"reachable": True, "observed": True,
                                                             "how": "stub"})

    record = port_diagnosis.observe(59996, service="postgres", container="abc", seconds=1.0)

    assert record["verdict"] == "undetermined"
    assert record["observations"]["wsl"].get("reachable") is None

    released.set()
    time.sleep(0.5)
    assert record["observations"]["wsl"].get("reachable") is None, \
        "a late answer must not rewrite a record that was already handed back"
    assert record["verdict"] == "undetermined"
    assert record["observations"]["wsl"]["why"] == "did_not_finish"
    assert record["still_running"] == ["wsl"], "the leftover worker is named, not silently dropped"


def test_the_container_lookup_is_inside_the_capture_budget(monkeypatch):
    """The defect this bites: the lookup ran before the budget started and was unbounded by it."""
    monkeypatch.setattr(port_diagnosis, "_tcp_from_wsl",
                        lambda port, seconds: {"reachable": True, "observed": True, "how": "stub"})
    monkeypatch.setattr(port_diagnosis, "_tcp_from_windows",
                        lambda port, seconds: {"reachable": True, "observed": True, "how": "stub"})
    monkeypatch.setattr(port_diagnosis, "_tcp_in_container",
                        lambda container, service, seconds: {"reachable": True, "observed": True,
                                                             "how": "stub"})
    offered = []

    def lookup(seconds):
        offered.append(seconds)
        time.sleep(0.4)
        return "abc123"

    started = time.monotonic()
    record = port_diagnosis.observe(59995, service="postgres", container_lookup=lookup, seconds=2.0)
    spent = time.monotonic() - started

    assert offered and offered[0] <= 2.0, "the lookup is given what is left of the budget, not its own"
    assert record["container_lookup"]["seconds"] >= 0.3
    assert record["container_lookup"]["found"] is True
    assert record["seconds"] >= record["container_lookup"]["seconds"]
    assert spent <= 6.0, "the whole capture, lookup included, stays inside one bound"
    assert record["deadline_seconds"] == 2.0


def test_a_lookup_that_fails_leaves_the_container_unasked_rather_than_guilty():
    def lookup(seconds):
        raise OSError("docker is not answering")

    record = port_diagnosis.observe(59994, service="redis", container_lookup=lookup, seconds=2.0)

    assert record["container_lookup"]["found"] is False
    assert record["observations"]["container"]["why"] == "no_container"
    assert record["verdict"] == "undetermined"


def test_the_record_says_how_long_after_the_failure_the_capture_began():
    """The claim is about an observation window that began measurably after the failure."""
    failed_at = time.monotonic() - 0.5
    record = port_diagnosis.observe(59993, service="redis", container=None, seconds=3.0,
                                    failed_at=failed_at)

    assert record["delay_from_failure_seconds"] >= 0.4
    assert "window" in record["note"] and "instant" in record["note"]


def test_the_networking_mode_is_carried_as_a_reference_not_as_a_measurement():
    """`context()` used to state NAT mode as an observed fact of the run. It never measured it."""
    where = port_diagnosis.context(0.0)

    assert where["wsl_networking_mode"] == "not measured by this capture"
    reference = where["reference"]
    assert reference["source"] and reference["observed_at"]
    assert "reference only" in reference["note"]


def test_a_command_that_failed_is_named_apart_from_a_reply_that_was_not_understood(monkeypatch):
    """Both observe nothing, and the record says which of the two happened."""
    prints(monkeypatch, "", 125)
    broke = port_diagnosis._tcp_in_container("deadbeef", "redis", 1.0)

    prints(monkeypatch, "some other program's greeting", 0)
    strange = port_diagnosis._tcp_in_container("deadbeef", "redis", 1.0)

    assert broke["why"] == "command_failed" and strange["why"] == "unrecognised_reply"
    assert broke["reachable"] is None and strange["reachable"] is None


def test_a_validated_refusal_records_the_form_it_matched_not_the_line(monkeypatch):
    prints(monkeypatch, "Could not connect to Redis at 127.0.0.1:6379: Connection refused", 1)

    record = port_diagnosis._tcp_in_container("deadbeef", "redis", 1.0)

    assert "127.0.0.1:6379" not in str(record), "the line itself is not copied"
    assert record["said"] == "Connection refused"
    assert record["reachable"] is False and record["observed"] is True


def test_a_probe_given_no_time_at_all_observes_nothing():
    """A socket asked with a zero budget refuses instantly. That is not the port refusing."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def eats_the_budget(seconds):
        time.sleep(0.4)
        return "abc123"

    try:
        record = port_diagnosis.observe(port, service="postgres", container_lookup=eats_the_budget,
                                        seconds=0.2)
    finally:
        listener.close()

    assert record["verdict"] == "undetermined"
    for name, observation in record["observations"].items():
        assert observation["reachable"] is None, name
        assert observation["why"] == "no_budget", name
