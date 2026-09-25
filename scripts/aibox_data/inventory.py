"""File inventory, sealed manifests and FileArtifacts store verification.

A manifest records every entry below each named root without following links: regular files carry
bytes and sha256, symlinks carry their literal target and whether it escapes the root (SPEC §8:
report links/external paths, never follow them). The manifest digest covers identities only; scan
time and mtimes are descriptive and excluded so an unchanged tree reproduces the same digest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import defaultdict
from pathlib import Path, PurePosixPath

from codex_harness.domain.model import canonical, utcnow

MANIFEST_SCHEMA = "zeus.aibox-data-manifest/1"
CHUNK = 1024 * 1024
ARTIFACT_BODY = re.compile(r"[0-9a-f]{64}\.txt")
ARTIFACT_META = re.compile(r"[0-9a-f]{64}\.json")
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}
WINDOWS_INVALID = re.compile(r'[<>:"\\|?*\x00-\x1f]')


def sha256_file(path: Path, limit: int | None = None) -> str:
    """Streamed sha256 of a file, or of its first `limit` bytes."""
    digest, remaining = hashlib.sha256(), limit
    with open(path, "rb") as stream:
        while remaining is None or remaining > 0:
            block = stream.read(CHUNK if remaining is None else min(CHUNK, remaining))
            if not block:
                break
            digest.update(block)
            if remaining is not None:
                remaining -= len(block)
    return digest.hexdigest()


def windows_name_problems(relative: str) -> list[str]:
    """Names a Windows restore (rollback R1) could not hold byte-for-byte."""
    problems = []
    for part in PurePosixPath(relative).parts:
        if WINDOWS_INVALID.search(part):
            problems.append("invalid_character")
        if part.endswith((".", " ")):
            problems.append("trailing_dot_or_space")
        if part.split(".")[0].casefold() in WINDOWS_RESERVED:
            problems.append("reserved_name")
    return sorted(set(problems))


def _escapes(root: Path, link_parent: Path, target: str) -> bool:
    if os.path.isabs(target) or re.match(r"^[A-Za-z]:[\\/]", target) or target.startswith("\\\\"):
        return True
    resolved = os.path.normpath(os.path.join(link_parent, target))
    return os.path.commonpath([str(root), resolved]) != str(root)


def scan_root(root: str | Path) -> dict:
    """Inventory one root without following symlinks. Unreadable entries are findings, not skips."""
    base = Path(root).absolute()
    if not base.is_dir():
        raise ValueError(f"root is not a directory: {root}")
    entries, unreadable = [], []
    stack = [base]
    while stack:
        folder = stack.pop()
        try:
            children = sorted(os.scandir(folder), key=lambda item: item.name)
        except OSError as exc:
            unreadable.append({"path": folder.relative_to(base).as_posix(), "error": type(exc).__name__})
            continue
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(base).as_posix()
            info = child.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                entries.append({"path": relative, "kind": "symlink", "link_target": target,
                                "escapes_root": _escapes(base, path.parent, target)})
            elif stat.S_ISDIR(info.st_mode):
                stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                try:
                    entries.append({"path": relative, "kind": "file", "bytes": info.st_size,
                                    "sha256": sha256_file(path), "mtime_ns": info.st_mtime_ns})
                except OSError as exc:
                    unreadable.append({"path": relative, "error": type(exc).__name__})
            else:
                entries.append({"path": relative, "kind": "special"})
    entries.sort(key=lambda item: item["path"])
    return {"entries": entries, "unreadable": sorted(unreadable, key=lambda item: item["path"]),
            "findings": findings(entries)}


def findings(entries: list[dict]) -> dict:
    folded = defaultdict(list)
    for entry in entries:
        folded[entry["path"].casefold()].append(entry["path"])
    return {
        "case_collisions": sorted(sorted(group) for group in folded.values() if len(group) > 1),
        "symlinks": [e["path"] for e in entries if e["kind"] == "symlink"],
        "external_symlinks": [e["path"] for e in entries if e.get("escapes_root")],
        "special_files": [e["path"] for e in entries if e["kind"] == "special"],
        "windows_incompatible": [{"path": e["path"], "problems": p} for e in entries
                                 if (p := windows_name_problems(e["path"]))],
    }


def _identity(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if key != "mtime_ns"}


def manifest_digest(manifest: dict) -> str:
    identity = {"schema": manifest["schema"], "migration_id": manifest["migration_id"],
                "roots": {name: {"source_label": root["source_label"],
                                 "entries": [_identity(e) for e in root["entries"]],
                                 "unreadable": root["unreadable"]}
                          for name, root in sorted(manifest["roots"].items())}}
    return "sha256:" + hashlib.sha256(canonical(identity).encode()).hexdigest()


def build_manifest(migration_id: str, roots: dict[str, str], host: str) -> dict:
    """Seal-able manifest over named roots. `roots` maps a stable root id to a local path."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", migration_id or ""):
        raise ValueError("invalid migration_id")
    if not roots:
        raise ValueError("at least one root is required")
    manifest = {"schema": MANIFEST_SCHEMA, "migration_id": migration_id, "host": host,
                "scanned_at": utcnow(), "roots": {}}
    for name, path in sorted(roots.items()):
        scanned = scan_root(path)
        files = [e for e in scanned["entries"] if e["kind"] == "file"]
        manifest["roots"][name] = {"source_label": Path(path).absolute().as_posix(), **scanned,
                                   "totals": {"files": len(files),
                                              "bytes": sum(e["bytes"] for e in files),
                                              "entries": len(scanned["entries"])}}
    manifest["digest"] = manifest_digest(manifest)
    return manifest


def verify_manifest_digest(manifest: dict) -> bool:
    return manifest.get("schema") == MANIFEST_SCHEMA and manifest.get("digest") == manifest_digest(manifest)


def blocking_findings(root: dict) -> dict:
    """Source findings that make a copy of this root unacceptable until explicitly decided: an
    unreadable subtree is unknown content (never an empty one), and special files or links that
    escape the root cannot be reproduced. Case collisions block only a Windows restore (R1)."""
    found = root.get("findings") or findings(root["entries"])
    return {"source_unreadable": sorted(e["path"] for e in root.get("unreadable", [])),
            "special_files": list(found["special_files"]),
            "external_symlinks": list(found["external_symlinks"])}


def compare_roots(expected: dict, actual: dict) -> dict:
    """Entry-level comparison of two scans of the same logical root (source vs copy). The expected
    side's blocking findings are carried through, so an unreadable source never compares equal."""
    want = {e["path"]: _identity(e) for e in expected["entries"]}
    have = {e["path"]: _identity(e) for e in actual["entries"]}
    mismatched = sorted(path for path in want.keys() & have.keys() if want[path] != have[path])
    result = {"missing": sorted(want.keys() - have.keys()), "extra": sorted(have.keys() - want.keys()),
              "mismatched": mismatched,
              "unreadable": sorted(e["path"] for e in actual.get("unreadable", [])),
              **blocking_findings(expected)}
    result["match"] = not any(result.values())
    return result


def validate_entry_path(relative: str) -> None:
    """Manifest paths are relative POSIX paths without empty, `.` or `..` components."""
    parts = relative.split("/") if isinstance(relative, str) else [""]
    if relative.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"unsafe manifest path: {relative!r}")


def verify_artifact_store(root: str | Path) -> dict:
    """Check a FileArtifacts root with the same rules as FileArtifacts.inspect: the body hash equals
    its name and `<key>.json` carries the same ref and byte count. Other files are only listed."""
    base = Path(root)
    bodies, metas, other = set(), set(), []
    for child in sorted(os.scandir(base), key=lambda item: item.name):
        if not child.is_file(follow_symlinks=False):
            other.append(child.name)
        elif ARTIFACT_BODY.fullmatch(child.name):
            bodies.add(child.name[:64])
        elif ARTIFACT_META.fullmatch(child.name):
            metas.add(child.name[:64])
        else:
            other.append(child.name)
    problems = []
    for key in sorted(bodies):
        body = base / f"{key}.txt"
        size = body.stat().st_size
        if sha256_file(body) != key:
            problems.append({"key": key, "problem": "body_hash_mismatch"})
            continue
        if key not in metas:
            problems.append({"key": key, "problem": "metadata_missing"})
            continue
        try:
            metadata = json.loads((base / f"{key}.json").read_text("utf-8"))
        except (OSError, ValueError):
            problems.append({"key": key, "problem": "metadata_invalid"})
            continue
        if not isinstance(metadata, dict) or metadata.get("ref") != "sha256:" + key:
            problems.append({"key": key, "problem": "metadata_ref_mismatch"})
        elif type(metadata.get("bytes")) is not int or metadata["bytes"] != size:
            problems.append({"key": key, "problem": "metadata_bytes_mismatch"})
    problems += [{"key": key, "problem": "orphan_metadata"} for key in sorted(metas - bodies)]
    return {"artifacts": len(bodies), "problems": problems, "unrecognised": other,
            "valid": not problems}


WINDOWS_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:(?:\\\\|\\|/)[^\s\"'<>|]*")


def scan_path_references(root: str | Path, max_bytes: int = 8 * 1024 * 1024, samples: int = 3) -> dict:
    """Report Windows absolute paths found in files. Evidence only: nothing is rewritten (SPEC §6)."""
    base = Path(root)
    hits, skipped = [], []
    for entry in scan_root(base)["entries"]:
        if entry["kind"] != "file":
            continue
        if entry["bytes"] > max_bytes:
            skipped.append(entry["path"])
            continue
        text = (base / entry["path"]).read_bytes().decode("utf-8", errors="replace")
        found = WINDOWS_PATH.findall(text)
        if found:
            hits.append({"path": entry["path"], "count": len(found), "samples": found[:samples]})
    return {"files_with_windows_paths": hits, "skipped_oversize": skipped}
