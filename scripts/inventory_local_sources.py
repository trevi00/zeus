"""Pin local reference trees and worktree drift without copying private file contents.

An inventory is a work queue, not a semantic review or an adoption approval.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True).stdout


def inventory(root: Path) -> dict:
    revision = git(root, "rev-parse", "HEAD").decode("ascii").strip()
    tree = git(root, "rev-parse", revision + "^{tree}").decode("ascii").strip()
    paths = []
    for entry in git(root, "ls-tree", "-r", "-l", "-z", revision).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid, size = metadata.decode("ascii").split()
        item = {"path_base64": base64.b64encode(raw_path).decode("ascii"),
                "mode": mode, "type": kind, "object": oid,
                "size": int(size) if size != "-" else None, "disposition": "unreviewed"}
        try:
            relative = raw_path.decode("utf-8")
            item["path"] = relative
            path = root / relative
            if mode == "160000":
                item["worktree_status"] = "submodule-not-inspected"
            elif path.is_symlink():
                item["worktree_sha256"] = hashlib.sha256(os.readlink(path).encode()).hexdigest()
                item["worktree_status"] = "symlink-not-followed"
            elif not path.is_file():
                item["worktree_status"] = "missing"
            else:
                with path.open("rb") as stream:
                    item["worktree_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                item["worktree_status"] = "hashed-not-reviewed"
        except (UnicodeError, OSError, ValueError):
            item["worktree_status"] = "unavailable-on-host"
        paths.append(item)
    if git(root, "rev-parse", "HEAD").decode("ascii").strip() != revision:
        raise RuntimeError("Reference HEAD changed during inventory; rerun")
    return {"version": 1, "revision": revision, "tree": tree, "tracked_paths": len(paths),
            "worktree_dirty": bool(git(root, "status", "--porcelain", "-z", "--untracked-files=no")),
            "coverage": "inventory-only; semantic review and execution pending",
            "worktree_hashes": "Observed live files, not a transactional snapshot or commit evidence",
            "paths": paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for source in args.source:
        name, separator, path = source.partition("=")
        if not separator or not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
            parser.error("Source must be a lowercase name=path pair")
        data = inventory(Path(path).resolve())
        output = args.output / f"{name}-{data['revision'][:12]}.json"
        text = json.dumps(data, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
        if output.exists():
            raise FileExistsError(f"Inventory already exists: {output}; choose a fresh output directory")
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        print(json.dumps({"source": name, "revision": data["revision"],
                          "paths": data["tracked_paths"], "dirty": data["worktree_dirty"],
                          "manifest": str(output), "sha256": hashlib.sha256(text.encode()).hexdigest()}))


if __name__ == "__main__":
    main()
