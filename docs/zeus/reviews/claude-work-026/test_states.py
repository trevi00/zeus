import socket
import threading

from codex_harness.adapters.verification import _Attempts


def test_starting_another_attempt_does_not_cancel_active_work():
    owner = _Attempts()
    registered = threading.Event()
    closed = threading.Event()
    release = threading.Event()

    class Resource:
        def close(self):
            closed.set()
            release.set()

    def work(register):
        register(Resource())
        registered.set()
        release.wait()

    first = owner.start(work, 'first')
    second = None
    try:
        assert registered.wait(2)
        second = owner.start(lambda register: release.wait(), 'second')
        assert not closed.wait(0.2), 'starting unrelated work reclaimed an active, non-timed-out attempt'
        assert not first.cancelled
    finally:
        release.set()
        first.thread.join(2)
        if second:
            second.thread.join(2)
        if first.reclaimer:
            first.reclaimer.join(2)


def test_reserved_slot_survives_until_worker_starts(monkeypatch):
    owner = _Attempts()
    paused = threading.Event()
    proceed = threading.Event()
    release = threading.Event()
    result = []
    original = threading.Thread.start

    def start(thread):
        if thread.name == 'verification-attempt-first-a0001':
            paused.set()
            proceed.wait(2)
        return original(thread)

    monkeypatch.setattr(threading.Thread, 'start', start)
    caller = threading.Thread(target=lambda: result.append(owner.start(lambda register: release.wait(), 'first')))
    caller.start()
    second = None
    try:
        assert paused.wait(2)
        second = owner.start(lambda register: release.wait(), 'second')
        assert 'a0001' in owner.slots, 'a reserved but not-started worker was misread as settled and removed'
    finally:
        proceed.set()
        release.set()
        caller.join(2)
        for attempt in result + ([second] if second else []):
            attempt.thread.join(2)
            if attempt.reclaimer:
                attempt.reclaimer.join(2)


def test_failed_closed_probe_is_not_positive_closure():
    owner = _Attempts()
    client, peer = socket.socketpair()

    class Resource:
        def fileno(self):
            raise OSError('review unable to inspect descriptor')

        def close(self):
            raise OSError('review close refused')

    resource = Resource()
    resource.socket = client
    attempt = owner.start(lambda register: register(resource), 'probe')
    try:
        attempt.thread.join(2)
        owner.finish(attempt)
        assert client.fileno() >= 0
        assert attempt.id in owner.slots, 'inspection failure was accepted as closed and freed the slot'
        assert not attempt.settled()
    finally:
        client.close()
        peer.close()
        if attempt.reclaimer:
            attempt.reclaimer.join(2)
