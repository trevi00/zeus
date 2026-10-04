"""The in-process access to the canonical offline tooling `scripts/aibox_data` (INV-HOST-MIGRATION-001).

Layer: composition
Owns: canonical_module
Does not own: the tool's location and refusal (`delivery.adapters.host_migration.canonical_tool`) and the typed runs (`run_canonical`)
Entry points: canonical_module
Contracts: INV-HOST-MIGRATION-001

The home S7 named for it: `delivery/adapters/host_migration.py` header ("Does not own: `canonical_module` (composition/canonical_tools.py: a dynamic import)") and `A/evidence/rebuild/s7/host-migration-adapter/transcribe.py:38`. The body is M7's `adapters/host_migration.py:103-110`
(SOURCE e38aa722) verbatim over the target `canonical_tool` (:104); a dynamic import of an external tool is a composition act, so `delivery.adapters` keeps none.
"""
from __future__ import annotations

import sys

from codex_harness.delivery.adapters.host_migration import canonical_tool


def canonical_module(name: str):
    """In-process access to a canonical helper (e.g. the stream-entries digest) for the exporters."""
    import importlib

    scripts = str(canonical_tool().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("aibox_data." + name)
