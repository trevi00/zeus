"""S9 integration (coordinator): the X3a resource rows render through the X2a exposition, and `observation_metrics` has
one writer (DESIGN-s9-X §2.2, §3).

The two halves were built in separate lanes against the same row shape; this checks the seam they share. It reads the
X3a fixture tree; nothing reaches the real host.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from _layout import TARGET, TESTS

from codex_harness.observation.adapters.metrics_exposition import render
from codex_harness.observation.adapters.resource_facts import ResourceFacts
from codex_harness.observation.application.metrics_projector import METRICS_BUCKET
from codex_harness.observation.ports import OWNED_BUCKETS

SRC = TARGET / "src" / "codex_harness"
FIXTURES = TESTS / "fixtures" / "s9_x3a"


def _statvfs(path):
    return SimpleNamespace(f_frsize=4096, f_blocks=1000, f_bavail=250, f_files=500, f_favail=125)


def test_resource_rows_render_as_text_exposition():
    units = {"worker": "system.slice/zeus-worker.service"}
    rows = ResourceFacts(cgroup_root=FIXTURES / "cgroup", proc_root=FIXTURES / "proc", units=units,
                         mounts={"runtime": "/runtime"}, interfaces=(), statvfs=_statvfs).rows()
    text = render(rows)
    lines = text.splitlines()
    for row in rows:
        assert f"# TYPE {row['metric']} {row['type']}" in lines
    assert 'zeus_filesystem_size_bytes{mount="runtime"} 4096000' in lines
    assert 'zeus_resource_fact_available{scope="runtime",fact="filesystem"} 1' in lines
    assert str(FIXTURES) not in text and "zeus-worker.service" not in text


def _put_sites(path: Path) -> list:
    sites = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "put" and node.args:
            first = node.args[0]
            if (isinstance(first, ast.Name) and first.id == "METRICS_BUCKET") or (
                    isinstance(first, ast.Constant) and first.value == METRICS_BUCKET):
                sites.append(node.lineno)
    return sites


def test_observation_metrics_is_declared_and_written_only_by_the_projector():
    assert OWNED_BUCKETS.count(METRICS_BUCKET) == 1 and METRICS_BUCKET == "observation_metrics"
    writers = {p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if _put_sites(p)}
    assert writers == {"observation/application/metrics_projector.py"}
