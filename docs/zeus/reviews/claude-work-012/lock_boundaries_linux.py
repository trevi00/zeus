"""Actual WSL/Linux filesystem counterexamples against the pinned pure-Python filelock package.

Pass means a defect reproduced. Temporary directories only; no model/DB or long-duration run.
"""
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

repo = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repo / 'src'))
# Reuse the lockfile-pinned pure Python package installed in the review environment.
# The package selects UnixFileLock from sys.platform; no Windows native extension is used.
sys.path.insert(0, str(repo / '.venv' / 'Lib' / 'site-packages'))
import filelock
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory, writer_alive
from codex_harness.domain.model import ContractError

assert platform.system() == 'Linux'
results = []
with tempfile.TemporaryDirectory(prefix='zeus-review-lock-owner-') as name:
    root = Path(name)
    run = '1' * 32
    owner = FileSpool(root, run, max_bytes=10000)
    other = FileSpool(root, run, max_bytes=10000)
    directory = SpoolDirectory(root)
    owner.append('event', {'event': 'owned'})
    directory.acknowledge(owner.path, owner.path.stat().st_size, 1)
    try:
        other.append('event', {'event': 'second-writer'})
    except ContractError:
        pass
    else:
        raise AssertionError('second writer should be refused')
    other.close()  # ordinary cleanup after the refused append
    assert writer_alive(root, run)
    assert directory.run_finished(run)
    pruned = directory.prune()
    assert pruned['segments'] == 1 and not owner.path.exists()
    assert owner.append('event', {'event': 'after-prune'}) > 0
    assert directory.spool_files() == []
    results.append({'case': 'non_owner_close', 'live_owner_pruned': True,
                    'next_append_success': True, 'collectable_segments': 0})
    owner.close()

with tempfile.TemporaryDirectory(prefix='zeus-review-lock-age-') as name:
    root = Path(name)
    run = '2' * 32
    spool = FileSpool(root, run, max_bytes=10000)
    spool.append('event', {'event': 'before-crash'})
    # Equivalent OS state to a dead process: no descriptor, no run lock, no closed marker.
    os.close(spool._descriptor)
    spool._descriptor = None
    spool._lock.release()
    spool._lock = None
    lock_path = root / 'spool' / (run + '.lock')
    lock_path.touch(exist_ok=True)
    old = time.time() - 8 * 86400
    for path in (spool.path, lock_path):
        os.utime(path, (old, old))
    directory = SpoolDirectory(root)
    age_before = directory.run_age(run)
    assert age_before > 7 * 86400
    assert not directory.run_finished(run)
    age_after = directory.run_age(run)
    assert age_after < 10
    assert not directory.run_finished(run)
    results.append({'case': 'probe_resets_retention', 'old_age_seconds': round(age_before),
                    'age_after_probe_seconds': round(age_after, 3), 'dead_run_reported_finished': False})

print(json.dumps({'platform': platform.platform(), 'filelock_version': filelock.__version__,
                  'lock_class': filelock.FileLock.__name__, 'results': results}))
