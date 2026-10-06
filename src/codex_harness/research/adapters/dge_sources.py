"""DGE source-binding verification over a passed Git source (INV-DGE-001).

Every source must be a regular blob at base whose bytes hash to the pinned digest. Directories, symlinks and
submodules are not regular blobs and are refused.

Layer: adapters
Context: research
Owns: `verify_sources`, the pure research rule that binds a DGE packet's sources to the base revision
Does not own: the Git source itself (the caller passes a `commit_exists`/`blob` object; no host_os import), the dge CLI
Entry points: verify_sources
Contracts: INV-DGE-001

Moved ahead of S10 from M7 `adapters/dge_cli.py` (:31-:45, SOURCE e38aa722) VERBATIM (DESIGN-s8 §9 V14): the body is M7's;
the only differences are the imports (`research.domain.dge`, `kernel.errors`) and the type-only `GitSource` annotation, which
is dropped so this module imports no host_os. The S10 CLIs import `verify_sources` from here.
"""
from __future__ import annotations

from codex_harness.kernel.errors import ContractError
from codex_harness.research.domain.dge import DgeRefused, source_binding


def verify_sources(packet: dict, source) -> list:
    """Every source must be a regular blob at base whose bytes hash to the pinned digest.
    Directories, symlinks and submodules are not regular blobs and are refused."""
    if not source.commit_exists(packet["base_revision"]):
        raise DgeRefused("base_revision_missing")
    bound = []
    for entry in packet["sources"]:
        mode, data = source.blob(packet["base_revision"], entry["path"])
        if mode is None:
            raise DgeRefused("source_missing_at_base")
        try:
            bound.append(source_binding(entry, mode, data))
        except ContractError as exc:
            raise DgeRefused("source_not_regular" if mode != "100644" else "source_digest_mismatch") from exc
    return bound
