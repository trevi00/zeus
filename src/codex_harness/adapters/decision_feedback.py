"""The trusted procedure registry, read from Git at an explicit commit (INV-DECISION-FEEDBACK-001).

The registry is owner-authored configuration that decides which observations are comparable, so it is
read through `GitSource` at a pinned 40-hex commit and never from the mutable working tree: editing the
checked-out file changes nothing until the change is committed and the new commit is named. The bytes
are bounded, parsed as strict JSON with duplicate keys refused, and validated by the domain registry
rules before any store is touched. No code from the registry is ever executed.
"""
from __future__ import annotations

import hashlib
import json

from codex_harness.adapters.operation_cli import GitSource
from codex_harness.domain.decision_feedback import (
    DecisionFeedbackError,
    RegistryError,
    registry_pin,
    validate_registry,
)
from codex_harness.domain.model import ContractError, digest, require

MAX_REGISTRY_BYTES = 256 * 1024
REGULAR_BLOB = "100644"


def load_registry(source: GitSource, revision: str, path: str) -> dict:
    """The pinned registry with the identity of the exact bytes it was read from, or a fixed code."""
    pin = registry_pin(revision, path)
    if not source.commit_exists(pin["revision"]):
        raise DecisionFeedbackError("registry_revision_missing")
    mode, data = source.blob(pin["revision"], pin["path"])
    if mode is None:
        raise DecisionFeedbackError("registry_missing_at_revision")
    if mode != REGULAR_BLOB:
        # A directory, symlink or submodule entry is not a registry file.
        raise DecisionFeedbackError("registry_not_regular")
    if len(data) > MAX_REGISTRY_BYTES:
        raise DecisionFeedbackError("registry_too_large")
    registry = validate_registry(_parse(data))
    return {"registry": registry, "revision": pin["revision"], "path": pin["path"],
            "sha256": hashlib.sha256(data).hexdigest(), "digest": digest(registry),
            "bytes": len(data), "entries": len(registry["entries"])}


def _parse(data: bytes) -> dict:
    """Bounded UTF-8 JSON with duplicate keys refused; the error names the file role, never content."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Procedure registry has a duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegistryError("Procedure registry is not valid JSON") from exc
    except ContractError as exc:
        raise RegistryError(str(exc)) from exc


__all__ = ["MAX_REGISTRY_BYTES", "load_registry"]
