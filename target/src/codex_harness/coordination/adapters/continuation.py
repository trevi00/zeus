"""The research evidence port of the conductor continuation: bounded, digest-checked reads of a receipt's evidence refs.

Layer: adapters
Context: coordination
Owns: `ResearchEvidence` and MAX_RESEARCH_EVIDENCE_BYTES (the trusted-store read with its fixed refusal codes)
Does not own: the store class (injected as `store_factory`: composition binds `storage.adapters.file_artifacts.FileArtifacts`), the configured root and the rest of M7 `adapters/continuation.py` (composition.continuation)
Entry points: ResearchEvidence
Contracts: INV-CONTINUATION-001

Moved from M7 `adapters/continuation.py:109-139` (SOURCE e38aa722) by named rule R-c27 (S10 unit C8b-1): the class is M7's verbatim except V-c27, the store class is the REQUIRED keyword `store_factory` instead of
the imported `FileArtifacts` (a coordination adapter may not import a storage adapter). Nothing else changes.
"""
from __future__ import annotations

from pathlib import Path

from codex_harness.coordination.domain.continuation import RESEARCH, ROUTE_OWNERS, ContinuationRefused
from codex_harness.kernel.errors import ContractError

MAX_RESEARCH_EVIDENCE_BYTES = 1024 * 1024  # the FileArtifacts.text ceiling


class ResearchEvidence:
    """The research evidence port over ONE trusted content-addressed store (`FileArtifacts`): `verify`
    reads at most `max_bytes` of the reference's actual bytes and checks their SHA-256. Refusals are
    fixed codes (`research_evidence_missing|unreadable|oversized|corrupt|invalid`); no path, raw error
    or content leaves. The root is fixed by configuration; it is never created, searched or
    supplied by a caller, and nothing is fetched. Integrity holds at the observed read only."""

    def __init__(self, root, max_bytes: int = MAX_RESEARCH_EVIDENCE_BYTES, *, store_factory):
        self.root, self.max_bytes, self.store = Path(root), max_bytes, None
        self.store_factory = store_factory

    def verify(self, reference) -> None:
        code = None
        try:
            if self.store is None:
                if not self.root.is_dir():
                    raise FileNotFoundError
                self.store = self.store_factory(str(self.root))
            self.store.text(reference, self.max_bytes)
        except FileNotFoundError:
            code = "research_evidence_missing"
        except UnicodeDecodeError:
            code = "research_evidence_invalid"  # digest matched, but not the text the store writes
        except OSError:
            code = "research_evidence_unreadable"
        except ContractError as exc:
            code = {"Artifact exceeds text budget": "research_evidence_oversized",
                    "Artifact modified": "research_evidence_corrupt"}.get(str(exc), "research_evidence_invalid")
        if code is not None:
            raise ContinuationRefused(code, ROUTE_OWNERS[RESEARCH], "evidence_refs")
