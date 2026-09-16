import threading
import time

import pytest

from codex_harness.adapters import port_diagnosis as diagnosis


def test_missing_container_is_unobserved_not_service_failure():
    # Real docker exec failure, not a database refusing a request.
    result = diagnosis._tcp_in_container('zeus-review-nonexistent-20260916', 'postgres', 3)
    assert result['reachable'] is None and result['observed'] is False, result


@pytest.mark.parametrize('values', [(False, None, True), (True, False, None), (None, True, False)])
def test_missing_vantage_prevents_localization(values):
    observations = dict(zip(diagnosis.VANTAGES, ({'reachable': value} for value in values)))
    assert diagnosis.narrow(observations) == 'undetermined'


def test_context_is_inside_capture_budget(monkeypatch):
    for name in ('_tcp_in_container', '_tcp_from_windows', '_tcp_from_wsl'):
        monkeypatch.setattr(diagnosis, name, lambda *args: {'reachable': True})

    import subprocess
    def bounded_command(*args, **kwargs):
        limit = kwargs['timeout']
        time.sleep(min(limit, 0.3))
        if limit < 0.3:
            raise subprocess.TimeoutExpired(args[0], limit)
        return subprocess.CompletedProcess(args[0], 0, stdout='review')
    monkeypatch.setattr(diagnosis.subprocess, 'run', bounded_command)
    started = time.monotonic()
    result = diagnosis.observe(59999, service='postgres', seconds=0.05)
    elapsed = time.monotonic() - started
    assert elapsed < 0.2, (elapsed, result['seconds'])


def test_returned_observations_are_frozen_after_deadline(monkeypatch):
    release = threading.Event()
    done = threading.Event()

    def late(*args):
        release.wait(2)
        done.set()
        return {'reachable': True}

    monkeypatch.setattr(diagnosis, '_tcp_from_wsl', late)
    monkeypatch.setattr(diagnosis, '_tcp_from_windows', lambda *args: {'reachable': True})
    monkeypatch.setattr(diagnosis, '_tcp_in_container', lambda *args: {'reachable': True})
    monkeypatch.setattr(diagnosis, 'context', lambda seconds: {})
    try:
        result = diagnosis.observe(59999, service='postgres', seconds=0.01)
        assert result['observations']['wsl']['reachable'] is None
    finally:
        release.set()
        assert done.wait(2)
        for worker in threading.enumerate():
            if worker.name.startswith('port-diagnosis-wsl'):
                worker.join(2)
    assert result['observations']['wsl']['reachable'] is None, result
