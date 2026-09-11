"""Windows/local regression counterexample: pass means an ownership violation reproduced."""
from pathlib import Path
import sys

repository = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repository / 'src'))

import pytest
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.domain.model import ContractError


def test_rejected_writer_cleanup_marks_live_owner_finished(tmp_path):
    run = '3' * 32
    owner = FileSpool(tmp_path, run, max_bytes=10000)
    other = FileSpool(tmp_path, run, max_bytes=10000)
    directory = SpoolDirectory(tmp_path)
    try:
        owner.append('event', {'x': 1})
        directory.acknowledge(owner.path, owner.path.stat().st_size, 1)
        with pytest.raises(ContractError):
            other.append('event', {'x': 2})
        other.close()
        assert directory.writer_alive(run)
        assert directory.run_finished(run)
        assert directory.reclaimable(owner.path)
    finally:
        owner.close()
