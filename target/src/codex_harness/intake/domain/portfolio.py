"""Portfolio refusal vocabulary (M7 `application/portfolio.PortfolioRefused`, moved ahead in S6 verbatim).

Layer: domain
Context: intake
Owns: PortfolioRefused (a fixed reason code and at most a field name, never a value)
Does not own: the Portfolio owner operations (intake.application, S8 completes them)
Entry points: PortfolioRefused
Contracts: INV-CONTINUATION-001
"""
from __future__ import annotations

from codex_harness.kernel.errors import ContractError


class PortfolioRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("portfolio refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field
