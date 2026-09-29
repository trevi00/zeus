"""The research adoption dispatch guard (INV-RESEARCH-004), moved ahead in S4.

Layer: domain
Context: research
Owns: research_origin and require_dispatch (M7 `domain/research.py`, moved ahead in S4 unchanged: the review
    decision unit refuses a research/proposal dispatch through it; other contexts receive it injected, §2.4)
Does not own: the audit contracts and parse_record of M7 `domain/research.py` (S8)
Entry points: require_dispatch, research_origin
Contracts: INV-RESEARCH-004
"""

from __future__ import annotations

from codex_harness.kernel.errors import require


def research_origin(value):
    if isinstance(value, dict):
        if any(k in value for k in ('source_url', 'research_provenance', 'audit_id', 'source_revision')):
            return True
        return any(research_origin(v) for v in value.values())
    if isinstance(value, list):
        return any(research_origin(v) for v in value)
    return False


def require_dispatch(details):
    # INV-RESEARCH-004: dormant rollout has no executable approval authority.
    # Legacy model verdicts and caller-supplied approval dictionaries cannot unlock it.
    if research_origin(details) or 'proposal' in details:
        require(False, 'Research adoption deferred: verified audit rollout is not active')
