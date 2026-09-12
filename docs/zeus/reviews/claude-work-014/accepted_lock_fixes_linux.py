"""Independent positive checks of the two previously reported defects on actual WSL files."""
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

repo = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repo / 'src'))
sys.path.insert(0, str(repo / '.venv' / 'Lib' / 'site-packages'))
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory, read_records
from codex_harness.domain.model import ContractError

assert platform.system() == 'Linux'
with tempfile.TemporaryDirectory(prefix='zeus-review-accepted-') as name:
    root = Path(name)
    run = '4' * 32
    owner = FileSpool(root, run, max_bytes=10000)
    other = FileSpool(root, run, max_bytes=10000)
    directory = SpoolDirectory(root)
    owner.append('event', {'x': 1})
    try:
        other.append('event', {'x': 2})
    except ContractError:
        pass
    else:
        raise AssertionError('second writer allowed')
    other.close()
    other.close()
    assert directory.writer_alive(run) and not directory.run_finished(run)
    assert directory.prune()['segments'] == 0
    owner.append('event', {'x': 3})
    assert [row[4]['x'] for row in read_records(owner.path)] == [1, 3]
    owner.close()
    try:
        owner.append('event', {'x': 4})
    except ContractError:
        pass
    else:
        raise AssertionError('closed owner resumed')

with tempfile.TemporaryDirectory(prefix='zeus-review-retention-') as name:
    root = Path(name)
    run = '5' * 32
    spool = FileSpool(root, run, max_bytes=10000)
    spool.append('event', {'x': 1})
    directory = SpoolDirectory(root)
    directory.acknowledge(spool.path, spool.path.stat().st_size, 1)
    os.close(spool._descriptor)
    spool._descriptor = None
    spool._lock.release()
    spool._lock = None
    old = time.time() - 8 * 86400
    os.utime(spool.path, (old, old))
    for _ in range(3):
        assert directory.run_finished(run) and directory.run_age(run) > 7 * 86400
    assert directory.prune()['segments'] == 1
    assert directory.known_runs() == set()
print(json.dumps({'platform': platform.platform(), 'non_owner_close_safe': True,
                  'owner_records_read_back': [1, 3], 'closed_append_refused': True,
                  'retention_unaffected_by_probes': True, 'dead_run_pruned': True}))
