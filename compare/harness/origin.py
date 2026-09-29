"""Module/wheel origin assertions for reference and target processes (REBUILD-DESIGN-v2 §5.2 R-O).

Layer: harness (never shipped)

Each side proves, inside its own process, that every loaded `codex_harness`/`zeus` module comes
from its own installation: the reference from the files its installed wheel RECORD lists, the
target from the target tree. `install_import_audit` additionally refuses such an import at
import time when its origin lies elsewhere, so a target never falls back to the reference.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import sys
from pathlib import Path

PACKAGES = ("codex_harness", "zeus")
DISTRIBUTION = "zeus-harness"


class OriginError(ImportError):
    pass


def _ours(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in PACKAGES)


def record_files(distribution: str = DISTRIBUTION) -> tuple[set[Path], dict]:
    """Absolute package file paths from the installed wheel RECORD, plus RECORD identity facts."""
    dist = importlib.metadata.distribution(distribution)
    files = set()
    record_bytes = b""
    package_rows = []
    for entry in dist.files or ():
        path = Path(dist.locate_file(entry)).resolve()
        if entry.name == "RECORD" and entry.parent.name.endswith(".dist-info"):
            record_bytes = path.read_bytes()
        top = entry.parts[0] if entry.parts else ""
        if top in PACKAGES:
            files.add(path)
            if entry.hash is not None:
                package_rows.append(f"{entry.as_posix()},{entry.hash.mode}={entry.hash.value}")
    facts = {
        "distribution": dist.metadata["Name"],
        "version": dist.version,
        "record_sha256": hashlib.sha256(record_bytes).hexdigest() if record_bytes else None,
        "package_files": len(package_rows),
        "package_files_digest": hashlib.sha256("\n".join(sorted(package_rows)).encode()).hexdigest(),
    }
    return files, facts


def loaded_origins() -> dict[str, str | None]:
    out = {}
    for name, module in sorted(sys.modules.items()):
        if module is None or not _ours(name):
            continue
        out[name] = getattr(module, "__file__", None)
    return out


def assert_record_origins(files: set[Path]) -> dict[str, str]:
    """Every loaded package module file must be listed in the installed RECORD."""
    bad, seen = {}, {}
    for name, file in loaded_origins().items():
        if file is None:
            bad[name] = "no __file__ (namespace or synthetic module)"
            continue
        path = Path(file).resolve()
        if path not in files:
            bad[name] = str(path)
        seen[name] = str(path)
    if bad:
        raise OriginError(f"R-O: modules outside the installed wheel RECORD: {bad}")
    return seen


def assert_tree_origins(root: Path) -> dict[str, str]:
    """Every loaded package module file must lie inside `root` (the target tree)."""
    root = root.resolve()
    bad, seen = {}, {}
    for name, file in loaded_origins().items():
        path = Path(file).resolve() if file else None
        if path is None or not path.is_relative_to(root):
            bad[name] = str(path)
        else:
            seen[name] = str(path.relative_to(root))
    if bad:
        raise OriginError(f"R-O: modules outside the target tree {root}: {bad}")
    return seen


class _AuditFinder(importlib.abc.MetaPathFinder):
    def __init__(self, roots: tuple[Path, ...]):
        self.roots = roots

    def find_spec(self, fullname, path=None, target=None):
        if not _ours(fullname):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None:
            return None
        origin = spec.origin
        locations = list(spec.submodule_search_locations or ())
        candidates = [Path(origin).resolve()] if origin and origin not in ("namespace",) else []
        candidates += [Path(p).resolve() for p in locations]
        if not candidates or not all(any(c.is_relative_to(r) for r in self.roots)
                                     for c in candidates):
            raise OriginError(f"R-O import audit: {fullname} resolves outside "
                              f"{[str(r) for r in self.roots]}: {[str(c) for c in candidates]}")
        return spec


def install_import_audit(*roots: Path) -> None:
    """Refuse any `codex_harness`/`zeus` import whose origin is outside the given roots."""
    resolved = tuple(Path(r).resolve() for r in roots)
    for finder in sys.meta_path:
        if isinstance(finder, _AuditFinder):
            finder.roots = resolved
            return
    sys.meta_path.insert(0, _AuditFinder(resolved))
