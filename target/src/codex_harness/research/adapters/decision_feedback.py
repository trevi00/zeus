"""The trusted procedure registry, read from Git at an explicit commit (INV-DECISION-FEEDBACK-001).

The registry is owner-authored configuration that decides which observations are comparable, so it is
read through `GitSource` at a pinned 40-hex commit and never from the mutable working tree: editing the
checked-out file changes nothing until the change is committed and the new commit is named. The bytes
are bounded, parsed as strict JSON with duplicate keys refused, and validated by the domain registry
rules before any store is touched. No code from the registry is ever executed.

Layer: adapters
Context: research
Owns: load_registry, the bounded read of the trusted procedure registry through an injected Git blob source at one pinned commit, its strict duplicate-key-refusing JSON parse and the identity (sha256, digest, bytes) of the exact bytes read
Does not own: the Git blob reader itself (host_os's GitSource, wired by composition behind research.ports.GitBlobSource), the registry rules (research.domain.decision_feedback), the collection application (a later layer) and the CLI (S10)
Entry points: load_registry, MAX_REGISTRY_BYTES
Contracts: INV-DECISION-FEEDBACK-001

Moved from M7 `adapters/decision_feedback.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §13 V18, A/evidence/rebuild/s8/hostos-adapters-move/transcribe.py): R-df0 (each name from the target home of the module that defines it), R-df1 (the `GitSource` annotation of the injected `source` is the research-declared `GitBlobSource` Protocol; the body is M7's); every other statement is M7's. The first paragraph is M7's module docstring.
"""
from __future__ import annotations

import hashlib
import json

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest
from codex_harness.research.domain.decision_feedback import (
    DecisionFeedbackError,
    RegistryError,
    registry_pin,
    validate_registry,
)
from codex_harness.research.ports import GitBlobSource

MAX_REGISTRY_BYTES = 256 * 1024
REGULAR_BLOB = "100644"


def load_registry(source: GitBlobSource, revision: str, path: str) -> dict:
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
