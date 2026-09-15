import socket
import threading

from codex_harness.adapters.verification import _Attempts, UNRECLAIMED_LIMIT
from codex_harness.domain.model import ContractError


def test_start_reserves_capacity_before_work_begins():
    owner = _Attempts()
    release = threading.Event()
    attempts = []
    try:
        for _ in range(UNRECLAIMED_LIMIT + 1):
            try:
                attempts.append(owner.start(lambda register: release.wait(), 'review'))
            except ContractError:
                break
        live = sum(attempt.thread.is_alive() for attempt in attempts)
        assert live <= UNRECLAIMED_LIMIT, f'{live} active attempts exceed cap before any reclaim completes'
    finally:
        release.set()
        for attempt in attempts:
            attempt.thread.join(2)


def test_failed_close_retains_real_socket_ownership():
    owner = _Attempts()
    client, peer = socket.socketpair()
    registered = threading.Event()
    release = threading.Event()

    class Resource:
        def close(self):
            release.set()
            raise OSError('review failed resource close')

    resource = Resource()
    resource.socket = client

    def work(register):
        register(resource)
        registered.set()
        release.wait()

    attempt = owner.start(work, 'review')
    try:
        assert registered.wait(2)
        report = owner.reclaim(attempt, 0.3)
        assert client.fileno() >= 0 and report['closed'] == 0
        assert not report['reclaimed'] and owner.outstanding(), 'failed close was dropped and reported reclaimed'
    finally:
        release.set()
        attempt.thread.join(2)
        client.close()
        peer.close()


def test_resource_registered_after_reclaim_window_is_still_managed():
    owner = _Attempts()
    allow_register = threading.Event()
    registered = threading.Event()
    closed = threading.Event()
    release = threading.Event()

    class Resource:
        def close(self):
            closed.set()
            release.set()

    def work(register):
        allow_register.wait()
        register(Resource())
        registered.set()
        release.wait()

    attempt = owner.start(work, 'review')
    try:
        report = owner.reclaim(attempt, 0.05)
        assert not report['reclaimed']
        allow_register.set()
        assert registered.wait(2)
        assert closed.wait(0.3), 'reclaim drain ended and later registration has no closer'
    finally:
        allow_register.set()
        release.set()
        attempt.thread.join(2)
