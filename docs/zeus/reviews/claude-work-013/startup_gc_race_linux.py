"""Actual WSL/Linux startup/GC race, with deterministic thread barriers at real lock/write calls.

No reused run id, forged closed marker, simulated filesystem, or elapsed-time sleep.
Successful completion means the reported unsafe interleaving reproduced.
"""
import json
import os
import platform
import sys
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

repo = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repo / 'src'))
sys.path.insert(0, str(repo / '.venv' / 'Lib' / 'site-packages'))
import filelock
import filelock._unix as unix
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory

assert platform.system() == 'Linux'
lock_created = threading.Event()
allow_acquire = threading.Event()
before_write = threading.Event()
allow_write = threading.Event()
wrote = threading.Event()
finish = threading.Event()
original_lock = unix._lock_fd_nonblocking
original_write = os.write
out = {}

def paused_lock(fd):
    if threading.current_thread().name == 'first-writer':
        lock_created.set()  # real lock pathname was opened, no flock acquired yet
        assert allow_acquire.wait(10)
    return original_lock(fd)

def paused_write(fd, data):
    if threading.current_thread().name == 'first-writer':
        before_write.set()  # run lock held; active segment open; no record written yet
        assert allow_write.wait(10)
    return original_write(fd, data)

with tempfile.TemporaryDirectory(prefix='zeus-review-startup-gc-') as name:
    root = Path(name)
    run = uuid4().hex
    writer = FileSpool(root, run, max_bytes=10000)
    directory = SpoolDirectory(root)
    original_finished = directory.run_finished

    def checked_then_writer_starts(*args, **kwargs):
        result = original_finished(*args, **kwargs)
        assert result  # lock-only candidate; no owner held the lock during the probe
        allow_acquire.set()
        assert before_write.wait(10)
        assert directory.writer_alive(run)
        return result  # GC continues using the earlier finished result

    def produce():
        try:
            out['offset'] = writer.append('event', {'event': 'first-real-record'})
            wrote.set()
            assert finish.wait(10)
        except BaseException as exc:
            out['error'] = type(exc).__name__ + ': ' + str(exc)
            wrote.set()
        finally:
            writer.close()

    unix._lock_fd_nonblocking = paused_lock
    os.write = paused_write
    directory.run_finished = checked_then_writer_starts
    thread = threading.Thread(target=produce, name='first-writer')
    thread.start()
    try:
        assert lock_created.wait(10)
        pruned = directory.prune()
        assert pruned['segments'] == 1
        assert directory.writer_alive(run)
        assert not writer.path.exists()
        allow_write.set()
        assert wrote.wait(10)
        assert 'error' not in out and out['offset'] > 0
        assert directory.spool_files() == []
        out.update(pruned=pruned, writer_alive=True, collectable_segments=0,
                   platform=platform.platform(), filelock_version=filelock.__version__)
    finally:
        allow_acquire.set()
        allow_write.set()
        finish.set()
        thread.join(10)
        unix._lock_fd_nonblocking = original_lock
        os.write = original_write
    assert not thread.is_alive()
print(json.dumps(out))
