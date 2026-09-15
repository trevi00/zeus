import socket
import threading

import pytest

from codex_harness.adapters.verification import VerificationServices


def test_timed_out_attempts_do_not_accumulate_live_io():
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(8)
    peers, workers, clients = [], [], []
    entered = threading.Event()

    def unanswered_request():
        worker = threading.current_thread()
        workers.append(worker)
        with socket.create_connection(server.getsockname(), timeout=1) as client:
            clients.append(client)
            client.settimeout(None)
            entered.set()
            client.recv(1)

    try:
        for _ in range(3):
            entered.clear()
            with pytest.raises(TimeoutError):
                VerificationServices._bounded(unanswered_request, 0.1)
            assert entered.is_set(), 'must reach actual connected socket read'
            peer, _ = server.accept()
            peers.append(peer)
        live = sum(thread.is_alive() for thread in workers)
        assert live == 0, f'three timed-out calls left {live} live worker threads and socket reads'
    finally:
        # Release only the test-owned peers so the abandoned workers can actually finish.
        for peer in peers:
            peer.shutdown(socket.SHUT_RDWR)
            peer.close()
        server.close()
        for worker in workers:
            worker.join(2)
        assert not any(worker.is_alive() for worker in workers)
