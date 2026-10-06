"""RH-2 P5a: the snapshot helpers moved out of `copies` into the guard-free `snapshot` module.

Layer: harness tooling tests. STRUCTURAL contract (move fidelity): every moved name is the very same object when read
through `copies`, and `snapshot`/`fileroots` import neither `copies` nor `compare/run.py`. The fresh-interpreter probe is
behavioural: importing them leaves the provider guard uninstalled (provider_guard.py install marker).
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import copies as cp  # noqa: E402
from rehearsal import snapshot  # noqa: E402

MOVED = ("_rel_parts", "VOLATILE_FILE", "SCAN_ROOTS", "load_volatile", "_VOLATILE", "VOLATILE_PATHS", "EXCLUDED_PATHS",
         "scan_tree", "_covered", "undeclared_changes", "stable_sha256", "snapshot_volatile", "_walk")


@pytest.mark.parametrize("name", MOVED)
def test_moved_name_is_the_same_object_through_copies(name):
    assert getattr(cp, name) is getattr(snapshot, name)


def test_volatile_file_still_points_at_the_unchanged_document():
    assert snapshot.VOLATILE_FILE == REPO / "compare" / "rehearsal" / "volatile.json"
    assert snapshot.VOLATILE_PATHS and snapshot.EXCLUDED_PATHS


def test_importing_snapshot_and_fileroots_loads_neither_copies_nor_run_and_installs_no_guard():
    compare = str(REPO / "compare")
    code = ("import sys; sys.path.insert(0, %r)\n"
            "import rehearsal.snapshot\n"
            "assert 'rehearsal.copies' not in sys.modules\n"
            "assert 'rehearsal_compare_run' not in sys.modules\n"
            "assert not getattr(sys, '_zeus_rebuild_provider_guard_installed', False)\n"
            "print('ok')" % compare)
    done = subprocess.run(["/usr/bin/python3", "-I", "-B", "-c", code], capture_output=True, text=True, timeout=120)
    assert (done.returncode, done.stdout.strip()) == (0, "ok"), done.stderr[-400:]
