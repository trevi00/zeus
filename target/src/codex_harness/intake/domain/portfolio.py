"""Portfolio refusal vocabulary (M7 `application/portfolio.PortfolioRefused`, moved ahead in S6 verbatim).

Layer: domain
Context: intake
Owns: PortfolioRefused (a fixed reason code and at most a field name, never a value) and `family_id`, the
    deterministic identity of one triage family (owner actions reads it)
Does not own: the Portfolio owner operations (intake.application, S8 completes them)
Entry points: PortfolioRefused, family_id
Contracts: INV-CONTINUATION-001
"""
from __future__ import annotations

from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest


class PortfolioRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("portfolio refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def family_id(status: str, reason_code: str) -> str:
    """Deterministic identity of one triage family, stable across processes and restarts."""
    return digest({"family_status": status, "reason_code": reason_code})
