"""Portfolio vocabulary: the refusal, the triage family identity and the constants research and owner actions read (INV-CONTINUATION-001).

Layer: domain
Context: intake
Owns: PortfolioRefused (a fixed reason code and at most a field name, never a value) and `family_id`, the
    deterministic identity of one triage family (owner actions reads it)
Does not own: the Portfolio owner operations (intake.application.portfolio, S8 pilot 63)
Entry points: PortfolioRefused, family_id, BUCKET_BINDINGS, BUCKET_INVESTIGATIONS, FAMILY_MINIMUM, RESEARCH_REQUIRED, PROGRESS_KIND, FAILURE_KIND
Contracts: INV-CONTINUATION-001

S6 moved `PortfolioRefused` and `family_id` ahead from M7 `application/portfolio.py` verbatim. S8 pilot 63 (SOURCE e38aa722, DESIGN-s8 V2c and §6 V11, A/evidence/rebuild/s8/portfolio-move/transcribe.py) adds R-p1 (the four constants research reads, M7's definitions, one owner here: the application imports them) and R-p2 (the two research kind values, intake-local; test_s8_portfolio_move pins them equal to research.domain).
"""
from __future__ import annotations

from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest

# One owner for what research and the owner-action families read from the Portfolio (DESIGN-s8 §1 R2, R-p1);
# M7 `application/portfolio.py` verbatim.
BUCKET_BINDINGS = "portfolio_bindings"
BUCKET_INVESTIGATIONS = "portfolio_investigations"
FAMILY_MINIMUM = 2
RESEARCH_REQUIRED = "research_required"

# Intake-local research vocabulary (DESIGN-s8 V2c, R-p2): the `portfolio_investigations` row kinds. Values from
# SOURCE; test_s8_portfolio_move pins them equal to research.domain.audit_progress.KIND and
# research.domain.research_investigations.KIND.
PROGRESS_KIND = "audit_progress"
FAILURE_KIND = "failure_family"


class PortfolioRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("portfolio refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def family_id(status: str, reason_code: str) -> str:
    """Deterministic identity of one triage family, stable across processes and restarts."""
    return digest({"family_status": status, "reason_code": reason_code})
