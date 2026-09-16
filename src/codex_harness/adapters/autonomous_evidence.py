"""Execution evidence port for the autonomous cycle (INV-AUTONOMOUS-001): the persisted execution
artifact behind an `execution_ref`, read through the same content-addressed FileArtifacts store the
executor wrote it to. Integrity (the bytes hash to the reference) is checked by the store; what the
artifact must prove (answer, reservation, stage, base, input evidence) is decided by the domain rule
`execution_evidence`, which the application applies together with the authoritative
`invocation_reservations` rows. Failures are fixed codes, never paths or contents.
"""
from __future__ import annotations

from codex_harness.domain.model import ContractError


class EvidenceUnavailable(ContractError):
    def __init__(self, reason_code: str):
        super().__init__("execution evidence " + reason_code)
        self.reason_code = reason_code


class ExecutionEvidence:
    """`document(ref)` -> the execution artifact as a dict; `evidence_missing`, `evidence_corrupt` or
    `evidence_invalid` otherwise. No provider, store or git access."""

    def __init__(self, artifacts):
        self.artifacts = artifacts

    def document(self, reference) -> dict:
        if not isinstance(reference, str):
            raise EvidenceUnavailable("evidence_missing")
        try:
            return self.artifacts.document(reference)
        except FileNotFoundError as exc:
            raise EvidenceUnavailable("evidence_missing") from exc
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise EvidenceUnavailable("evidence_corrupt") from exc
        except ContractError as exc:
            # "Artifact modified", "Invalid artifact reference", "Evidence document must be an object".
            raise EvidenceUnavailable("evidence_corrupt" if "modified" in str(exc) else "evidence_invalid") from exc
