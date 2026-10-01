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
    """In-process access to a canonical helper (e.g. the stream-entries digest) for the exporters.

    Counted rule (S7 pilot 44, import rules forbid a non-literal dynamic import): M7's
    `importlib.import_module("aibox_data." + name)` is a literal table of the SOURCE `scripts/aibox_data` modules; any
    other name raises M7's `ModuleNotFoundError` (same message and `name`)."""
    import importlib

    scripts = str(host_migration.canonical_tool().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    load = _MODULES.get(name)
    if load is None:
        raise ModuleNotFoundError(f"No module named 'aibox_data.{name}'", name=f"aibox_data.{name}")
    return load(importlib)


_MODULES = {
    "cli": lambda importer: importer.import_module("aibox_data.cli"),
    "contracts": lambda importer: importer.import_module("aibox_data.contracts"),
    "gates": lambda importer: importer.import_module("aibox_data.gates"),
    "inventory": lambda importer: importer.import_module("aibox_data.inventory"),
    "mapping": lambda importer: importer.import_module("aibox_data.mapping"),
    "transfer": lambda importer: importer.import_module("aibox_data.transfer"),
}
