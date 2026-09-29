"""Staging a pinned candidate for a writable container, and validating/importing its stopped output.

Layer: adapters
Context: execution
Owns: `list_revision` (the pinned tree read by host git from the real checkout), `stage_source` (export:
    validated first, materialized after, with the caller's own heartbeat between files),
    `init_standalone_git` (a minimal repository: no remote, no hook, nothing from the host's .git),
    `scan_tree` (the output as regular files only), `plan_import`/`apply_import` (complete validation,
    then contained, re-hashed copy into the real candidate)
Does not own: the path/size rules (execution.domain.staging_rules), process creation (the injected
    host_os `ChildProcesses` port), the container (owned_container)
Entry points: list_revision, stage_source, init_standalone_git, scan_tree, plan_import, apply_import,
    PREPARATION_TICK_SECONDS
Contracts: INV-ROLE-CONTAINER-001

Moved from SOURCE M7 `adapters/isolated_worker` (the staging half), characterized first by the
`containers.staging` golden: symlinks and submodules refuse (never inert copies), a heartbeat refusal
stops the export before the next file and before any container, and nothing that changed after
validation is imported (I1 (f)5: partial output is never promoted).
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import threading
import time
from pathlib import Path

from codex_harness.execution.domain.container_spec import MAX_FILE_BYTES, MAX_FILES
from codex_harness.execution.domain.staging_rules import GENERATED, check_bounds, check_relative_path
from codex_harness.kernel.errors import IsolationError, require
from codex_harness.kernel.ids import digest

# How often source preparation calls the caller's existing lease heartbeat while it materializes
# files. It is a cadence, not a deadline or a renewal of its own: the caller's callback keeps its
# own renewal interval and its own ownership checks.
PREPARATION_TICK_SECONDS = 1.0


def list_revision(repository, revision: str, *, processes) -> list:
    """[(mode, sha, size, path)] of the pinned candidate, read by host git from the REAL checkout."""
    listing = processes.run(["git", "-C", str(repository), "ls-tree", "-r", "-z", "-l", "--full-tree", revision],
                            capture_output=True, timeout=120)
    if listing.returncode != 0:
        raise IsolationError("source_revision_unavailable")
    entries = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, raw = record.partition(b"\t")
        mode, kind, sha, size = meta.decode("ascii").split()
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IsolationError("source_path_unsafe", "path is not UTF-8") from exc
        if kind != "blob" or mode not in ("100644", "100755"):
            # 120000 symlink, 160000 submodule and anything else: explicit refusal, never inert copies.
            raise IsolationError("source_entry_unsupported", mode + " " + repr(name)[:200])
        entries.append((mode, sha, int(size), name))
    return entries


def stage_source(repository, revision: str, destination: Path, *, processes, on_progress=None) -> dict:
    """Export the pinned revision into a fresh directory: validated first, materialized after.

    `on_progress` is the caller's OWN lease and cancellation heartbeat, called as this export makes
    progress (once the pinned entries are known, then at most every `PREPARATION_TICK_SECONDS` of
    materialization, then once the manifest is complete). It is passed through unchanged: nothing here
    extends a deadline, renews anything itself or weakens an ownership check, and a caller that passes
    no callback behaves exactly as before. An exception from the callback (an ended, superseded or
    cancelled execution) propagates immediately, so the export stops before the next file and before
    any container exists.
    """
    entries = list_revision(repository, revision, processes=processes)
    bounds = check_bounds([(name, size) for _, _, size, name in entries])
    tick = (lambda: None) if on_progress is None else on_progress
    tick()
    destination = Path(destination)
    require(not destination.exists(), "Staging directory must be fresh")
    destination.mkdir(parents=True)
    root = destination.resolve()
    reader = processes.popen(["git", "-C", str(repository), "cat-file", "--batch"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def request():
        try:
            reader.stdin.write(b"".join(sha.encode("ascii") + b"\n" for _, sha, _, _ in entries))
            reader.stdin.close()
        except OSError:
            pass
    writer = threading.Thread(target=request, daemon=True)
    writer.start()
    manifest = {}
    beat = time.monotonic()
    try:
        for mode, sha, size, name in entries:
            now = time.monotonic()
            if now - beat >= PREPARATION_TICK_SECONDS:
                # Between two files, never inside one: the bytes, hash, path and ownership rules
                # of the file being written are untouched by the heartbeat's cadence.
                tick()
                beat = now
            header = reader.stdout.readline().split()
            if len(header) != 3 or header[0].decode("ascii") != sha or header[1] != b"blob" or int(header[2]) != size:
                raise IsolationError("source_read_failed", repr(name)[:200])
            data = reader.stdout.read(size)
            if len(data) != size or reader.stdout.read(1) != b"\n":
                raise IsolationError("source_read_failed", repr(name)[:200])
            target = root.joinpath(*name.split("/"))
            require(root in target.resolve().parents, "Unsafe source path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if mode == "100755":
                target.chmod(0o755)
            manifest[name] = hashlib.sha256(data).hexdigest()
    finally:
        reader.kill()
        reader.wait(timeout=20)
        writer.join(timeout=5)
        reader.stdout.close()
    tick()   # the last beat before the caller leaves preparation and may create a container
    return {"revision": revision, **bounds, "manifest": manifest, "manifest_sha256": digest(manifest)}


def init_standalone_git(staging: Path, *, processes) -> dict:
    """A minimal repository for the worker's read-only git commands: no remote, no hook, nothing from
    the host's .git. Host git touches this directory only here, before the worker exists."""
    base = ["git", "-C", str(staging), "-c", "core.autocrlf=false", "-c", "core.hooksPath=", "-c", "core.fileMode=false",
            "-c", "user.name=Zeus Staging", "-c", "user.email=staging@localhost", "-c", "commit.gpgsign=false"]
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "HOME", "USERPROFILE")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    for args in (["init", "-q"], ["add", "-A", "-f"], ["commit", "-q", "--no-verify", "-m", "staged candidate"]):
        result = processes.run([*base, *args], capture_output=True, timeout=600, env=env)
        if result.returncode != 0:
            raise IsolationError("source_git_init_failed", args[0])
    return {"initialized": True, "remotes": 0, "hooks": "none", "note": "host git is never run here again"}


def scan_tree(root: Path, *, skip_top_git: bool = True) -> dict:
    """{relative path: sha256} of the regular files under `root`, or a refusal. Links, devices,
    hardlinks, nested .git, unsafe names, collisions and oversize all refuse; the staged top-level
    .git and generated caches are excluded and never read or executed."""
    root = Path(root)
    found, sizes, stack = {}, [], [(root, ())]
    while stack:
        directory, parts = stack.pop()
        with os.scandir(directory) as listing:
            for entry in listing:
                relative = (*parts, entry.name)
                if (skip_top_git and relative == (".git",)) or entry.name in GENERATED:
                    continue
                info = entry.stat(follow_symlinks=False)
                name = "/".join(relative)
                reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                if entry.is_symlink() or stat.S_ISLNK(info.st_mode) or reparse:
                    raise IsolationError("output_link_refused", repr(name)[:200])
                if stat.S_ISDIR(info.st_mode):
                    check_relative_path(name)
                    stack.append((Path(entry.path), relative))
                    continue
                if entry.name.endswith((".pyc", ".pyo")):
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise IsolationError("output_special_file_refused", repr(name)[:200])
                if info.st_nlink > 1:
                    raise IsolationError("output_hardlink_refused", repr(name)[:200])
                sizes.append((name, info.st_size))
                if len(sizes) > MAX_FILES:
                    raise IsolationError("source_too_many_files")
                found[name] = entry.path
    check_bounds(sizes)
    hashed = {}
    for name, path in found.items():
        data = Path(path).read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise IsolationError("source_file_too_large", repr(name)[:200])
        hashed[name] = hashlib.sha256(data).hexdigest()
    return hashed


def plan_import(manifest: dict, staging: Path) -> dict:
    """Complete validation of the stopped container's output; nothing is written by this step."""
    after = scan_tree(staging)
    added = sorted(name for name in after if name not in manifest)
    modified = sorted(name for name in after if name in manifest and after[name] != manifest[name])
    deleted = sorted(name for name in manifest if name not in after)
    return {"added": added, "modified": modified, "deleted": deleted, "after_sha256": digest(after),
            "hashes": {name: after[name] for name in (*added, *modified)}}


def apply_import(plan: dict, staging: Path, candidate: Path) -> dict:
    """Copy validated regular bytes into the real candidate. Every target is contained and is never
    reached through a link; bytes are re-hashed so nothing that changed after validation enters."""
    staging, root = Path(staging), Path(candidate).resolve()
    for name in (*plan["added"], *plan["modified"], *plan["deleted"]):
        target = root.joinpath(*check_relative_path(name))
        if root not in target.resolve().parents or target.is_symlink():
            raise IsolationError("import_target_unsafe", repr(name)[:200])
    for name in (*plan["added"], *plan["modified"]):
        data = staging.joinpath(*name.split("/")).read_bytes()
        if hashlib.sha256(data).hexdigest() != plan["hashes"][name]:
            raise IsolationError("import_changed_after_validation", repr(name)[:200])
        target = root.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name in plan["deleted"]:
        root.joinpath(*name.split("/")).unlink(missing_ok=True)
    return {key: plan[key] for key in ("added", "modified", "deleted", "after_sha256")}
