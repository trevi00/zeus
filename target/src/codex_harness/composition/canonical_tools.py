"""In-process access to the canonical offline tooling's helper modules (M7 `adapters/host_migration.canonical_module`).

Layer: composition
Owns: `canonical_module`
Does not own: the canonical tool's location (`delivery.adapters.host_migration.canonical_tool`), the exporters that use
    the helper (they take it as the required `canonical_module` argument)
Entry points: canonical_module
Contracts: INV-HOST-MIGRATION-001
"""
from __future__ import annotations

import sys

from codex_harness.delivery.adapters import host_migration


def canonical_module(name: str):
    """In-process access to a canonical helper (e.g. the stream-entries digest) for the exporters."""
    import importlib

    scripts = str(host_migration.canonical_tool().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("aibox_data." + name)
