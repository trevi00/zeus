"""The in-process access to the canonical offline tooling `scripts/aibox_data` (INV-HOST-MIGRATION-001).

Layer: composition
Owns: canonical_module
Does not own: the tool's location and refusal (`delivery.adapters.host_migration.canonical_tool`) and the typed runs (`run_canonical`)
Entry points: canonical_module
Contracts: INV-HOST-MIGRATION-001

The home S7 named for it: `delivery/adapters/host_migration.py` header ("Does not own: `canonical_module` (composition/canonical_tools.py: a dynamic import)") and `A/evidence/rebuild/s7/host-migration-adapter/transcribe.py:38`.
Rule R-e5c-ct (S10 unit E5c, owner decision of resume 2). Declared difference from M7 `adapters/host_migration.py:103-110` (SOURCE e38aa722): M7 imported the tool module in-process (`importlib.import_module("aibox_data." + name)` after a `sys.path` edit).
`tests/import_rules.py:184-191` refuses a non-literal dynamic import and `aibox_data` is not an allowed external, so there is no import here. `canonical_tool()` still runs first (M7's typed refusal when the tool is absent stays). The one product consumer,
`redis_inventory` (`delivery/adapters/host_migration.py:567-569`), needs only `contracts.stream_entries_sha256`: it is returned in a read-only namespace, its body `scripts/aibox_data/contracts.py:146-148` verbatim over the same
`codex_harness.kernel.ids.canonical` that the tool imports (`contracts.py:18`). Any other module name is refused (`canonical_tool_unavailable`). `tests/test_s10_e5cd_entries.py` pins the function to the tool's.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

from codex_harness.delivery.adapters.host_migration import canonical_tool
from codex_harness.delivery.domain.host_migration import MigrationRefused
from codex_harness.kernel.ids import canonical


def stream_entries_sha256(entries: list) -> str:
    """The E4 `entries_sha256`: canonical JSON of the XRANGE - + result as [[id, {field: value}]]."""
    return hashlib.sha256(canonical([[entry_id, dict(fields)] for entry_id, fields in entries]).encode()).hexdigest()


_CONTRACTS = SimpleNamespace(stream_entries_sha256=staticmethod(stream_entries_sha256))


def canonical_module(name: str):
    """Access to the canonical helper the exporters use: `contracts` only; any other name is refused."""
    canonical_tool()
    if name != "contracts":
        raise MigrationRefused("canonical_tool_unavailable", "scripts/aibox_data")
    return _CONTRACTS
