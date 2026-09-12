"""Independent real-filesystem ordering checks; no model or operating service calls."""
import importlib
import json
import os
import platform
import sys
import tempfile
import threading
from pathlib import Path

repo = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repo / 'src'))
if os.name != 'nt':
    sys.path.insert(0, str(repo / '.venv' / 'Lib' / 'site-packages'))
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory, read_records, run_lock_path

native = importlib.import_module('filelock._windows' if os.name == 'nt' else 'filelock._unix')
results = []
for order in ('writer_first', 'gc_first'):
    with tempfile.TemporaryDirectory(prefix='zeus-independent-') as name:
        root = Path(name)
        run = '8' * 32
        directory = SpoolDirectory(root)
        spool = FileSpool(root, run, max_bytes=10000)
        reached, release, written, finish, gc_done = [threading.Event() for _ in range(5)]
        errors = []
        original_lock = native._lock_fd_nonblocking
        original_finished = directory.run_finished
        calls = [0]

        def paused_lock(fd):
            if threading.current_thread().name == 'writer':
                calls[0] += 1
                if order == 'writer_first' and calls[0] == 2:
                    reached.set()
                    assert release.wait(8)
            return original_lock(fd)

        def paused_finished(*args):
            result = original_finished(*args)
            if order == 'gc_first':
                assert result
                reached.set()
                assert release.wait(8)
            return result

        def produce():
            try:
                spool.append('event', {'sequence': 1})
                written.set()
                assert finish.wait(8)
                spool.append('event', {'sequence': 2})
            except BaseException as exc:
                errors.append(repr(exc))
            finally:
                spool.close()

        def collect():
            try:
                directory.prune()
                gc_done.set()
            except BaseException as exc:
                errors.append(repr(exc))

        native._lock_fd_nonblocking = paused_lock
        directory.run_finished = paused_finished
        writer = threading.Thread(target=produce, name='writer')
        gc = threading.Thread(target=collect, name='gc')
        try:
            if order == 'writer_first':
                writer.start()
                assert reached.wait(8)
                gc.start()
                assert not gc_done.wait(0.3), 'GC passed a registering writer'
            else:
                run_lock_path(root, run).parent.mkdir(parents=True)
                run_lock_path(root, run).touch()
                gc.start()
                assert reached.wait(8)
                writer.start()
                assert not written.wait(0.3), 'writer passed GC decision/delete boundary'
            release.set()
            assert written.wait(8) and gc_done.wait(8)
            assert spool.path.exists()
            assert directory.writer_alive(run)
            finish.set()
        finally:
            release.set()
            finish.set()
            writer.join(10)
            gc.join(10)
            native._lock_fd_nonblocking = original_lock
        assert not errors, errors
        assert not writer.is_alive() and not gc.is_alive()
        rows = [r[4]['sequence'] for r in read_records(spool.path)]
        assert rows == [1, 2], rows
        results.append({'order': order, 'read_back': rows, 'safe': True})
print(json.dumps({'platform': platform.platform(), 'checks': results}))
