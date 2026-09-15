import threading
import time

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import VerificationServices, UNRECLAIMED_LIMIT
import codex_harness.adapters.verification as module


def service(tmp_path):
    return VerificationServices(tmp_path / 'services', FileArtifacts(tmp_path / 'artifacts'))


def test_new_instances_do_not_reset_live_attempt_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'RECLAIM_SECONDS', 0.02)
    release = threading.Event()
    workers = []

    def work(register):
        workers.append(threading.current_thread())
        release.wait()

    try:
        for _ in range(UNRECLAIMED_LIMIT + 1):
            try:
                service(tmp_path)._bounded(work, 0.02)
            except Exception:
                pass
        live = sum(worker.is_alive() for worker in workers)
        assert live <= UNRECLAIMED_LIMIT, f'new instances reset the cap: {live} workers remain alive'
    finally:
        release.set()
        for worker in workers:
            worker.join(2)
        assert not any(worker.is_alive() for worker in workers)


def test_blocking_close_is_inside_reclaim_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'RECLAIM_SECONDS', 0.02)
    release = threading.Event()
    closing = threading.Event()
    finished = threading.Event()
    workers = []

    class Resource:
        def close(self):
            closing.set()
            release.wait()

    def work(register):
        workers.append(threading.current_thread())
        register(Resource())
        release.wait()

    def invoke():
        try:
            service(tmp_path)._bounded(work, 0.02)
        except Exception:
            pass
        finally:
            finished.set()

    caller = threading.Thread(target=invoke)
    caller.start()
    try:
        assert closing.wait(2)
        assert finished.wait(0.3), 'close is synchronous outside both readiness and reclaim bounds'
    finally:
        release.set()
        caller.join(2)
        for worker in workers:
            worker.join(2)
        assert not caller.is_alive()


def test_registration_after_reclaim_started_is_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'RECLAIM_SECONDS', 0.05)
    sweep_started = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    workers = []
    svc = service(tmp_path)
    original = svc._close_all

    def close_all(resources):
        result = original(resources)
        sweep_started.set()
        return result

    monkeypatch.setattr(svc, '_close_all', close_all)

    class Resource:
        def close(self):
            closed.set()
            release.set()

    def work(register):
        workers.append(threading.current_thread())
        sweep_started.wait()
        register(Resource())
        release.wait()

    try:
        with pytest.raises(TimeoutError):
            svc._bounded(work, 0.02)
        assert closed.is_set(), 'late registered resource was never closed or retried'
    finally:
        release.set()
        for worker in workers:
            worker.join(2)
