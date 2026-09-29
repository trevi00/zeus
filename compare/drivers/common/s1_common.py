"""Shared helpers for the S1 scenario bodies (REBUILD-DESIGN-v2 §5.2 R-C/R-D, §5.3 S1).

Layer: harness (never shipped); standard library only.

A scenario body in this directory never imports `codex_harness`: each side's driver imports its own
implementation and hands the body an `api` namespace, so the reference and the target run the SAME
steps with the same deterministic inputs in separate processes. Results carry outcomes, field
names, statuses, digests and sizes; host paths are replaced by symbolic roots and no payload is
printed beyond the fixed fixture text the scenario itself wrote.
"""

from __future__ import annotations

import hashlib


def outcome(action) -> dict:
    """`{"ok": value}` or the refusal as `{"error": <type>, "message": <text>, ...}`."""
    try:
        value = action()
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 - the refusal type and reason are the result
        row = {"error": type(exc).__name__, "message": str(exc)[:400]}
        for attr in ("reason_code", "cause", "code"):
            if hasattr(exc, attr) and isinstance(getattr(exc, attr), (str, int, type(None))):
                row[attr] = getattr(exc, attr)
        return row
    return {"ok": value}


def sha(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def relative(value, roots: dict):
    """Replace every root path (longest first) by `<NAME>` inside strings, lists and dicts."""
    ordered = sorted(roots.items(), key=lambda kv: -len(kv[1]))
    if isinstance(value, dict):
        return {k: relative(v, roots) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [relative(v, roots) for v in value]
    if isinstance(value, str):
        for name, root in ordered:
            value = value.replace(root, "<" + name + ">")
        return value
    return value
