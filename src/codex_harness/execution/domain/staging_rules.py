"""Portable path and size rules for a staged candidate and a worker's output (pure).

Layer: domain
Context: execution
Owns: `check_relative_path` (a path safe on Linux and on a Windows host alike), `check_bounds` (counts,
    sizes and case collisions, files against directories too), the generated-cache names never read
Does not own: reading Git or the filesystem (execution.adapters.containers.staging)
Entry points: check_relative_path, check_bounds, GENERATED, WINDOWS_RESERVED, WINDOWS_UNSAFE
Contracts: INV-ROLE-CONTAINER-001

Moved from SOURCE M7 `adapters/isolated_worker` (the pure staging rules), characterized first by the
`containers.staging` golden.
"""

from __future__ import annotations

import re

from codex_harness.execution.domain.container_spec import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES
from codex_harness.kernel.errors import IsolationError

GENERATED = ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}
WINDOWS_UNSAFE = re.compile(r'[<>:"\\|?*\x00-\x1f]')


def check_relative_path(name: str) -> tuple:
    """A path that is safe on Linux and on a Windows host alike, or a refusal."""
    if type(name) is not str or not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise IsolationError("source_path_unsafe", repr(name)[:200])
    parts = tuple(name.split("/"))
    for part in parts:
        if (part in ("", ".", "..") or WINDOWS_UNSAFE.search(part) or part.endswith((".", " "))
                or part.split(".")[0].upper() in WINDOWS_RESERVED or part.lower() == ".git"):
            raise IsolationError("source_path_unsafe", repr(name)[:200])
    return parts


def check_bounds(entries) -> dict:
    """`entries` is [(path, bytes)]: counts, sizes and case collisions, files against directories too."""
    if len(entries) > MAX_FILES:
        raise IsolationError("source_too_many_files", str(len(entries)))
    seen, directories, total = set(), set(), 0
    for name, size in entries:
        parts = check_relative_path(name)
        if size > MAX_FILE_BYTES:
            raise IsolationError("source_file_too_large", repr(name)[:200])
        total += size
        if total > MAX_TOTAL_BYTES:
            raise IsolationError("source_too_large")
        folded = "/".join(parts).casefold()
        if folded in seen:
            raise IsolationError("source_case_collision", repr(name)[:200])
        seen.add(folded)
        for depth in range(1, len(parts)):
            directories.add(("/".join(parts[:depth]).casefold(), "/".join(parts[:depth])))
    spelled = {}
    for folded, actual in directories:
        if folded in seen or spelled.setdefault(folded, actual) != actual:
            raise IsolationError("source_case_collision", repr(actual)[:200])
    return {"files": len(entries), "bytes": total}
