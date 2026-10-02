"""Shared S9 scenario steps (`observation.frontend_bytes`, static): the sha256 manifest of the monitor frontend and the packaged observatory assets.

Layer: harness (never shipped)

`api.frontend` is the side's `frontend/monitor` directory and `api.resources` the side's `codex_harness/resources` directory. The manifest lists every
file under `frontend/monitor/` and the five packaged resources (`monitor.html`, `observatory/**`) with its size and sha256: the design's "unchanged
bytes; built assets packaged as target resources" (§3.1) as a recorded fact. Only bytes are read; nothing is executed or built.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def entry(path: Path) -> dict:
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def listing(root: Path, paths) -> dict:
    return {p.relative_to(root).as_posix(): entry(p) for p in sorted(paths) if p.is_file()}


def run(api) -> dict:
    frontend = listing(api.frontend, api.frontend.rglob("*"))
    resources = listing(api.resources, [api.resources / "monitor.html", *(api.resources / "observatory").rglob("*")])
    return {"frontend_monitor": frontend, "packaged_resources": resources,
            "counts": {"frontend_monitor": len(frontend), "packaged_resources": len(resources)}}
