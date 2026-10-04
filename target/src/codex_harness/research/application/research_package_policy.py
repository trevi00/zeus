"""The research-first admission policy over research packages (GAP #20; DESIGN-s10 §14 G20-D5).

Layer: application
Context: research
Owns: ResearchPackagePolicy.admit (the ten ordered steps and their reason codes)
Does not own: the holding record that persists a non-admitting answer (coordination.application.research_admission),
    the package store (research_packages), the pin lookup (the ResearchPins port; composition implements it)
Entry points: ResearchPackagePolicy.admit
Contracts: INV-RESEARCH-001, INV-RESEARCH-004 (addendum A1 v2 RF-RT)

`admit(tx, lease, action)` answers `{"disposition": admit|exempt|research|blocked, "reason"}` and reads only. It never
raises for a lease-data problem: an exemption refusal, a research-key conflict or a supersession refusal becomes
`blocked` with its code (CE-9: never an invented admission). The steps run in this order:
 1 exemption -> exempt `exempt:<class>`;           2 no package for the key -> research `package_missing`;
 3 not accepted -> research `package_not_accepted`; 4 supersession cycle/missing target -> blocked
 `package_supersession_cycle|missing` (the chain is followed to find the current package, so it is resolved between
 steps 2 and 3); 5 an unopened/unavailable source -> blocked `source_unavailable`; 6 fewer than 3 sources -> blocked
 `insufficient_sources`, or, with a recorded gap, the final reason becomes `admit_with_source_gap` (steps 7-9 still
 apply: a gap excuses missing sources, not a stale or contradicted package); 7 a pinned source whose current pin
 differs -> research `stale_version`, unknown -> blocked `pin_unavailable`; 8 accepted longer than `max_age_days` ago ->
 research `stale_age`; 9 an unresolved material contradiction -> blocked `material_contradiction`; 10 admit `admitted`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from codex_harness.kernel.errors import ContractError
from codex_harness.research.application.research_packages import PackageRefused
from codex_harness.research.domain.research_package import (
    RESEARCH_PACKAGE_MAX_AGE_DAYS,
    ResearchExemptionRefused,
    exemption,
    research_key,
)

MINIMUM_SOURCES = 3


def _answer(disposition: str, reason: str) -> dict:
    return {"disposition": disposition, "reason": reason}


def accepted_at(package: dict) -> datetime | None:
    events = [event for event in package.get("history", []) if event.get("event") == "accepted"]
    try:
        return datetime.fromisoformat(events[-1]["at"]) if events else None
    except (KeyError, ValueError, TypeError):
        return None


class ResearchPackagePolicy:
    def __init__(self, packages, pins, *, clock, max_age_days: int = RESEARCH_PACKAGE_MAX_AGE_DAYS):
        self.packages, self.pins, self.clock, self.max_age_days = packages, pins, clock, max_age_days

    def admit(self, tx, lease: dict, action: str) -> dict:
        try:
            exempt = exemption(lease)
        except ResearchExemptionRefused as refusal:
            return _answer("blocked", refusal.code)
        if exempt is not None:
            return _answer("exempt", "exempt:" + exempt["class"])
        try:
            key = research_key(lease)
        except ContractError as refusal:
            return _answer("blocked", "research_key_conflict" if "Conflicting" in str(refusal)
                           else "research_key_invalid")
        try:
            package = self.packages.current(tx, key)
        except PackageRefused as refusal:
            return _answer("blocked", refusal.reason_code)
        if package is None:
            return _answer("research", "package_missing")
        if package["status"] != "accepted":
            return _answer("research", "package_not_accepted")
        sources = package["sources"]
        if any(not (source["opened"] and source["available"]) for source in sources):
            return _answer("blocked", "source_unavailable")
        gap = len(sources) < MINIMUM_SOURCES
        if gap and package["source_gap"] is None:
            return _answer("blocked", "insufficient_sources")
        for source in sources:
            if source["pin_ref"] is None:
                continue
            pinned = self.pins.current(source["pin_ref"])
            if pinned is None:
                return _answer("blocked", "pin_unavailable")
            if pinned != source["applicable_version"]:
                return _answer("research", "stale_version")
        accepted = accepted_at(package)
        if accepted is None or self.clock.now() - accepted > timedelta(days=self.max_age_days):
            return _answer("research", "stale_age")
        if any(item["material"] and item["resolved_ref"] is None for item in package["contradictions"]):
            return _answer("blocked", "material_contradiction")
        return _answer("admit", "admit_with_source_gap" if gap else "admitted")
