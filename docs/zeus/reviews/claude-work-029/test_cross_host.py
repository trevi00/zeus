import json
import os
import queue
import subprocess
import threading

import pytest

from codex_harness.adapters import published_ports


@pytest.mark.skipif(os.name != 'nt', reason='Windows caller with real WSL peer required')
def test_windows_selection_excludes_preexisting_wsl_occupant():
    # No Docker or system configuration changes. WSL holds a real bound socket before choose().
    script = '''import socket,sys
held=None
for port in range(24000,24100):
 try:
  s=socket.socket();s.bind(('127.0.0.1',port));held=s;break
 except OSError:
  s.close()
if held is None:raise SystemExit(3)
print(port,flush=True)
sys.stdin.readline()
held.close()
'''
    peer = subprocess.Popen(['wsl.exe', '-d', 'Ubuntu', '--', 'python3', '-u', '-c', script],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ready = queue.Queue()
    reader = threading.Thread(target=lambda: ready.put(peer.stdout.readline()), daemon=True)
    reader.start()
    try:
        port = int(ready.get(timeout=15).strip())

        class Candidate:
            def randint(self, low, high):
                assert low <= port <= high
                return port

        chosen = published_ports.choose(1, rng=Candidate())
        print(json.dumps({'wsl_already_bound': port, 'windows_chosen': chosen}))
        assert chosen['ports'] is None or port not in chosen['ports'], 'Windows accepted a port already held in WSL'
    finally:
        try:
            peer.communicate(input=b'finish\n', timeout=5)
        except subprocess.TimeoutExpired:
            peer.kill()
            peer.communicate(timeout=5)
        reader.join(2)
