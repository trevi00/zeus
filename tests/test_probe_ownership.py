"""What the measurement tooling is allowed to delete, and what it has to say when it cannot.

Codex's R2 (review 5217822946): the first version of `scripts/wsl_port_probe.py` ran `docker rm -f`
on a **fixed name** before creating anything, and its measurement functions had no `finally` around
the whole resource lifetime. Two of them running at once could delete each other's container, and a
timeout in the middle skipped the last removal. The docstring meanwhile said every run used unique
names and touched nothing else.

These run against real disposable containers, because the claim is about what docker actually does.
They never name anything that could belong to an operational stack: every container here is created
by the probe itself with a fresh uuid and a `zeus.probe` label, and only ids captured at creation are
removed.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess

import pytest

PROBE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "wsl_port_probe.py"
docker_only = pytest.mark.skipif(os.environ.get("ZEUS_TEST_DOCKER") != "1",
                                 reason="Explicit disposable Docker validation required")


@pytest.fixture(scope="module")
def probe():
    """The probe as a real module, so its own `run` can be replaced to reach the failure paths."""
    spec = importlib.util.spec_from_file_location("zeus_wsl_port_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alive(container_id):
    done = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container_id],
                          capture_output=True, text=True, timeout=60)
    return done.returncode == 0 and (done.stdout or "").strip() == "true"


def exists(container_id):
    done = subprocess.run(["docker", "inspect", container_id], capture_output=True, text=True,
                          timeout=60)
    return done.returncode == 0


def free_port(probe):
    return probe.a_port_both_sides_draw_from()


def test_two_containers_of_the_same_run_never_share_a_name(probe):
    """Unique by construction, so a second run cannot address the first one's container."""
    names = {probe.Container(1).name for _ in range(50)}
    assert len(names) == 50
    assert all(name.startswith("zeus-probe-") for name in names)


@docker_only
def test_a_second_probe_does_not_take_the_first_ones_container(probe):
    """The defect this bites: deleting by a fixed name took whatever was wearing it."""
    first = probe.Container(free_port(probe))
    with first:
        assert first.id, "the first container should have started"
        second = probe.Container(free_port(probe))
        with second:
            assert second.id and second.id != first.id
            assert alive(first.id), "starting a second probe must leave the first one running"
        assert second.cleanup["removed"] is True
        assert alive(first.id), "and removing the second must leave the first one running"
    assert first.cleanup["removed"] is True
    assert not exists(first.id)


@docker_only
def test_a_failure_in_the_middle_still_removes_what_this_run_created(probe):
    """A timeout or an observation blowing up must not skip the removal."""
    box = probe.Container(free_port(probe))
    created = None
    with pytest.raises(RuntimeError):
        with box:
            created = box.id
            assert created and alive(created)
            raise RuntimeError("an observation failed the way a timeout would")

    assert box.cleanup["attempted"] is True and box.cleanup["removed"] is True
    assert not exists(created)


@docker_only
def test_a_start_that_never_happened_deletes_nothing(probe):
    """A failed start does not license deleting whatever happens to carry the name."""
    listener = __import__("socket").socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    taken = listener.getsockname()[1]
    try:
        box = probe.Container(taken)
        with box:
            assert box.id is None, "the daemon should refuse this port"
        assert box.cleanup["attempted"] is False
        assert box.cleanup["error"] == "nothing_was_created"
    finally:
        listener.close()


@docker_only
def test_a_container_already_gone_is_still_reported_as_removed(probe):
    """`docker rm -f` answers 0 for something already gone, and gone is what was claimed."""
    box = probe.Container(free_port(probe))
    with box:
        created = box.id
        assert created
        subprocess.run(["docker", "rm", "-f", created], capture_output=True, timeout=60)

    assert box.cleanup["attempted"] is True and box.cleanup["removed"] is True
    assert not exists(created)


def test_a_removal_that_cannot_happen_is_reported_rather_than_assumed(probe, monkeypatch):
    """The reporting path itself: a removal that fails must not read as a removal that worked."""
    box = probe.Container(1)
    box.id = "0123456789ab"                       # as if a creation had handed this back

    monkeypatch.setattr(probe, "run", lambda argv, timeout=120: (1, "", "No such container"))
    box.__exit__(None, None, None)
    assert box.cleanup == {"attempted": True, "removed": False, "error": "remove_failed"}

    box.cleanup = {"attempted": False, "removed": None, "error": None}

    def explodes(argv, timeout=120):
        raise OSError("the daemon is not answering")

    monkeypatch.setattr(probe, "run", explodes)
    box.__exit__(None, None, None)
    assert box.cleanup["attempted"] is True and box.cleanup["removed"] is False
    assert box.cleanup["error"] == "OSError"


@docker_only
def test_the_occupant_socket_is_released_even_when_the_body_raises(probe):
    import socket as socket_module

    port = free_port(probe)
    occupant = probe.Occupant(port)
    with pytest.raises(RuntimeError):
        with occupant:
            raise RuntimeError("the measurement failed while the port was held")

    again = socket_module.socket()
    try:
        again.bind(("127.0.0.1", port))      # free again, so the occupant really let go
    finally:
        again.close()


def test_every_report_carries_what_the_cleanup_did(probe):
    box = probe.Container(1)
    report = box.report()
    assert set(report) >= {"name", "started", "start_exit", "cleanup"}
    assert set(report["cleanup"]) == {"attempted", "removed", "error"}
