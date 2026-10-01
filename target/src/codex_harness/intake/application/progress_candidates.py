"""The audit-progress candidate row of `portfolio_investigations`: the owner's read and write for another context.

Layer: application
Context: intake
Owns: the read and the write of ONE `audit_progress` candidate row of `portfolio_investigations`, for research's AuditProgress (S8 pilot 72, R-ap1)
Does not own: the candidate row's body (research.domain.audit_progress builds it), the failure-family rows (intake.application.portfolio)
Entry points: ProgressCandidates
Contracts: INV-AUDIT-PROGRESS-001
"""

from __future__ import annotations

from codex_harness.intake.domain.portfolio import BUCKET_INVESTIGATIONS


class ProgressCandidates:
    """Moved from M7 `AuditProgress._candidate` (`tx.get`/`tx.put` of BUCKET_INVESTIGATIONS), the row unchanged. Stateless."""

    def progress_candidate(self, tx, identifier: str):
        return tx.get(BUCKET_INVESTIGATIONS, identifier)

    def record_progress_candidate(self, tx, identifier: str, row: dict) -> None:
        tx.put(BUCKET_INVESTIGATIONS, identifier, row)
