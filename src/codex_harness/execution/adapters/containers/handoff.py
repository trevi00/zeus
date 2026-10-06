"""The immutable evidence hand-off (D4): a writer's settled evidence into the content-addressed store, and a
verified, read-only per-run copy of exactly the handed-off artifacts for a reviewer container.

Layer: adapters
Context: execution
Owns: `retain_evidence_handoff` (copy a settled writer's `/evidence` tree and retained inner result into
    the artifact store; refusals are recorded, never raised), `handoff_refs` (the artifact refs a turn
    may read: named refs and paths present in the store, plus each named hand-off manifest's files),
    `materialize_handoff` (the per-run verified read-only copy, laid out like the store), `discard_tree`
    (this context's own per-run trees: the Codex home, hand-off copy and task state)
Does not own: the artifact store (storage; an object with `put(text, source) -> {"ref"}` is passed in),
    the output scan rule (staging.scan_tree), the credential copy's settlement (credentials: its broker
    removes the per-run home it settled with its own `discard_tree`; the DAG gives the two contexts no
    shared adapter, and the kernel holds no IO)
Entry points: retain_evidence_handoff, handoff_refs, materialize_handoff, discard_tree, HANDOFF_KIND
Contracts: INV-ROLE-CONTAINER-001

Moved from SOURCE M7 `adapters/role_containers` (the hand-off half), characterized first by the
`containers.staging` golden (I1 (f)3: evidence is handed off immutably after the writer settles; no live
shared writable source, no link escape; a digest mismatch or an oversize set refuses before any container).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

from codex_harness.execution.adapters.containers.staging import scan_tree
from codex_harness.kernel.errors import IsolationError, require
from codex_harness.kernel.ids import canonical, digest

HANDOFF_KIND = "zeus-evidence-handoff-v1"
MAX_HANDOFF_REFS, MAX_HANDOFF_BYTES, MAX_MANIFEST_BYTES = 512, 256 * 1024 * 1024, 8 * 1024 * 1024
REF = re.compile(r"sha256:([0-9a-f]{64})")
# A hand-off named inside a referenced receipt (the writer's execution receipt carries its isolation block).
NAMED_HANDOFF = re.compile(r'"evidence_handoff":\s*\{[^{}]*?"manifest":\s*"sha256:([0-9a-f]{64})"')


def retain_evidence_handoff(artifacts, evidence_dir, run_id: str) -> dict:
    """Copy a settled writer's evidence (its `/evidence` tree and retained inner result) into the
    content-addressed store and return the manifest reference. Links, special files, hardlinks and
    oversize refuse by name (recorded, never raised: the writer's imported result stands)."""
    evidence_dir = Path(evidence_dir)
    try:
        tree = scan_tree(evidence_dir, skip_top_git=False)
        sources = {name: evidence_dir.joinpath(*name.split("/")) for name in tree}
        inner = evidence_dir.parent / "inner_result.json"
        if inner.is_file() and not inner.is_symlink():
            sources["result/inner_result.json"] = inner
        files, total = {}, 0
        for name in sorted(sources):
            data = sources[name].read_bytes()
            if name in tree and hashlib.sha256(data).hexdigest() != tree[name]:
                raise IsolationError("handoff_changed_after_scan", repr(name)[:200])
            try:
                text, encoding = data.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                text, encoding = base64.b64encode(data).decode("ascii"), "base64"
            receipt = artifacts.put(text, "isolated-evidence:" + run_id + ":" + name)
            files[name] = {"ref": receipt["ref"], "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                           "encoding": encoding}
            total += len(data)
        manifest = {"kind": HANDOFF_KIND, "run_id": run_id, "files": files}
        receipt = artifacts.put(canonical(manifest), "isolated-evidence-handoff:" + run_id)
    except IsolationError as exc:
        return {"manifest": None, "refused": exc.reason_code}
    except Exception as exc:  # the writer's imported result stands; a failed copy is named, never raised
        return {"manifest": None, "refused": "handoff_" + type(exc).__name__}
    return {"manifest": receipt["ref"], "files": len(files), "bytes": total}


def handoff_refs(root, texts) -> list:
    """The artifact refs a container turn may read: every `sha256:<hex>` or `<root>/<hex>.txt` named
    in the host-assembled texts that exists in the store, plus each named hand-off manifest's files."""
    root = Path(root)
    found = set()
    path_pattern = re.compile(re.escape(str(root)) + r"[/\\]([0-9a-f]{64})\.txt")
    for text in texts:
        found.update(REF.findall(text))
        found.update(path_pattern.findall(text))
    present = {key for key in found if (root / (key + ".txt")).is_file()}

    def text_of(key):
        path = root / (key + ".txt")
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        return path.read_bytes().decode("utf-8", errors="replace")
    manifests = set()
    for key in sorted(present):
        text = text_of(key)
        if text is not None:
            manifests.update(name for name in NAMED_HANDOFF.findall(text) if (root / (name + ".txt")).is_file())
            manifests.add(key)
    for key in sorted(manifests):
        try:
            body = json.loads(text_of(key) or "null")
        except ValueError:
            continue
        if isinstance(body, dict) and body.get("kind") == HANDOFF_KIND and isinstance(body.get("files"), dict):
            present.add(key)
            for entry in body["files"].values():
                match = REF.fullmatch(str(entry.get("ref") if isinstance(entry, dict) else ""))
                if match and (root / (match.group(1) + ".txt")).is_file():
                    present.add(match.group(1))
    return ["sha256:" + key for key in sorted(present)]


def materialize_handoff(handoff: dict | None, destination: Path) -> dict | None:
    """A per-run, verified, read-only copy of exactly the handed-off artifacts, laid out like the
    store so the same absolute paths and the artifact reader work inside the container. Never the
    live store, never a link; a digest mismatch or an oversize set refuses before any container."""
    if not handoff or not handoff.get("refs"):
        return None
    root = Path(handoff["root"])
    require(root.is_absolute() and "," not in str(root), "The hand-off root must be an absolute path")
    refs = list(handoff["refs"])
    if len(refs) > MAX_HANDOFF_REFS:
        raise IsolationError("handoff_too_large", str(len(refs)) + " refs")
    destination = Path(destination)
    destination.mkdir(parents=True)
    total = 0
    for ref in refs:
        match = REF.fullmatch(str(ref))
        if match is None:
            raise IsolationError("handoff_ref_invalid", repr(ref)[:100])
        source = root / (match.group(1) + ".txt")
        info = os.lstat(source)
        if not stat.S_ISREG(info.st_mode):
            raise IsolationError("handoff_source_not_regular", match.group(1))
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != match.group(1):
            raise IsolationError("handoff_integrity_failed", match.group(1))
        total += len(data)
        if total > MAX_HANDOFF_BYTES:
            raise IsolationError("handoff_too_large", str(total) + " bytes")
        target = destination / (match.group(1) + ".txt")
        target.write_bytes(data)
        target.chmod(0o444)
    destination.chmod(0o555)
    return {"source": str(destination.resolve()), "target": str(root),
            "summary": {"refs": len(refs), "bytes": total, "refs_sha256": digest(sorted(refs))}}


def discard_tree(path) -> None:
    """Remove a per-run directory this layer created, including read-only copies it made."""
    path = Path(path)
    if not path.exists():
        return
    for directory, _, _ in os.walk(path):
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)
