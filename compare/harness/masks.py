"""The closed, versioned mask list (REBUILD-DESIGN-v2 §5.2 R-D) and its application.

Layer: harness (never shipped)

`compare/masks.json` may hold only three kinds of entry: `alpha_rename` (generated identifiers,
equality relations preserved), `host_path` (absolute host paths -> symbolic roots) and
`nondeterministic_os` (pids, monotonic readings, temporary names that cannot be injected). Owners,
generations, attempts, leases, statuses, authorization results, digests and refs are never masked;
`validate` refuses a mask that targets one of them. Adding a mask needs Codex review.
"""

from __future__ import annotations

import json
from pathlib import Path

MASKS_FILE = Path(__file__).resolve().parents[1] / "masks.json"
KINDS = frozenset({"alpha_rename", "host_path", "nondeterministic_os"})
NEVER_MASKED = ("owner", "lease_owner", "generation", "attempt", "lease", "lease_until", "status",
                "authorized", "authorization", "digest", "sha256", "ref", "context_ref",
                "manifest_hash", "evidence_ref", "decision", "verdict")


def load(path: Path = MASKS_FILE) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    validate(document)
    return document


def validate(document: dict) -> None:
    if document.get("closed") is not True or not isinstance(document.get("version"), int):
        raise ValueError("masks.json must be closed and versioned")
    ids = set()
    for mask in document.get("masks", []):
        if mask.get("kind") not in KINDS:
            raise ValueError(f"mask {mask.get('id')}: kind {mask.get('kind')!r} is not allowed")
        if mask["id"] in ids:
            raise ValueError(f"duplicate mask id {mask['id']}")
        ids.add(mask["id"])
        if not mask.get("reason") or not mask.get("scenarios"):
            raise ValueError(f"mask {mask['id']}: reason and scenarios are required")
        if mask["kind"] != "host_path":
            leaf = mask["field"].rsplit(".", 1)[-1]
            if leaf in NEVER_MASKED or leaf.endswith(("_digest", "_ref", "_sha256")):
                raise ValueError(f"mask {mask['id']}: field {mask['field']!r} is never masked")


class Masker:
    """Applies the masks declared for one scenario family to one case."""

    def __init__(self, scenario: str, document: dict | None = None, roots: dict | None = None):
        document = document or load()
        self.masks = [m for m in document["masks"] if scenario in m["scenarios"]]
        self.roots = dict(sorted((roots or {}).items(), key=lambda kv: -len(kv[1])))
        self.alpha: dict[str, dict] = {}

    def _field_masks(self, path: tuple[str, ...]):
        for mask in self.masks:
            if mask["kind"] == "host_path":
                continue
            parts = tuple(mask["field"].split("."))
            if path[-len(parts):] == parts:
                yield mask

    def _value(self, mask: dict, value):
        if mask["kind"] == "alpha_rename":
            names = self.alpha.setdefault(mask["id"], {})
            key = json.dumps(value, sort_keys=True, default=str)
            names.setdefault(key, f"<{mask['id']}:{len(names) + 1}>")
            return names[key]
        return f"<{mask['id']}>"

    def _string(self, value: str) -> str:
        if any(m["kind"] == "host_path" for m in self.masks):
            for name, root in self.roots.items():
                value = value.replace(root, "<" + name + ">")
        return value

    def apply(self, value, path: tuple[str, ...] = ()):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                child = path + (str(key),)
                masks = list(self._field_masks(child))
                out[key] = self._value(masks[0], item) if masks else self.apply(item, child)
            return out
        if isinstance(value, (list, tuple)):
            return [self.apply(item, path) for item in value]
        if isinstance(value, str):
            return self._string(value)
        return value
