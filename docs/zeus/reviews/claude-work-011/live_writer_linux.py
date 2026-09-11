"""Actual WSL/Linux filesystem counterexample, stdlib only; no model or PG simulation claim."""
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

repo = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repo / 'src'))
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory

assert platform.system() == 'Linux'
with tempfile.TemporaryDirectory(prefix='zeus-review-live-') as name:
    root = Path(name)
    spool = FileSpool(root, '1' * 32, max_bytes=100000, segment_bytes=10000)
    directory = SpoolDirectory(root)
    spool.append('event', {'event': 'before_idle'})
    directory.acknowledge(spool.path, spool.path.stat().st_size, 1)
    old = time.time() - 8 * 86400
    os.utime(spool.path, (old, old))  # controlled inactivity/clock boundary, no eight-day wait claimed
    pruned = directory.prune()
    assert pruned['segments'] == 1 and not spool.path.exists()
    offset = spool.append('event', {'event': 'after_idle'})
    assert offset > 0 and directory.spool_files() == []
    print(json.dumps({'platform': platform.platform(), 'pruned': pruned,
                      'writer_still_open': spool._descriptor is not None,
                      'append_reported_success': True, 'visible_segments': 0,
                      'scope': 'live writer unlinked by age; later successful append has no collectable path'}))
    spool.close()
