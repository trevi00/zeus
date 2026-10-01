"""Packaged policy and the evaluator factory for proactive discovery pressure (INV-DISCOVERY-PRESSURE-001).

The thresholds are the packaged document's (3 and 1, labelled `suggested_unconfirmed`: the user's initial
suggestion, not a confirmed constant); no caller supplies a numeric default.

Layer: adapters
Context: research
Owns: the packaged policy document read and the evaluator factory over a store
Does not own: the evaluator (research.application.discovery_pressure), the call ledger and the census read (injected by the composition)
Entry points: packaged_policy, pressure
Contracts: INV-DISCOVERY-PRESSURE-001

Moved from M7 `adapters/discovery_pressure.py` (SOURCE e38aa722) through one named rule (DESIGN-s8 §10 V15, A/evidence/rebuild/s8/discovery-pressure-move/transcribe.py): R-dp2 (`pressure` passes the injected `ledger` and `census` to `DiscoveryPressure`; the lazy `CallBudget` import is removed, the composition supplies the ledger); `packaged_policy` is M7's. The first paragraphs are M7's module docstring.
"""
from __future__ import annotations

import json
from importlib.resources import files

POLICY_RESOURCE = "discovery-pressure-policy.json"


def packaged_policy() -> dict | None:
    """The packaged document, or None when it cannot be read (the evaluator then holds proactive discovery)."""
    try:
        return json.loads(files("codex_harness.resources").joinpath(POLICY_RESOURCE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pressure(store, observer, *, ledger=None, census=None):
    """The evaluator over THIS process's store. In a lane process that store has no Fleet registry, so
    pressure reads as unregistered and holds proactive discovery: a lane store never stands in for the
    control store's pressure."""
    from codex_harness.research.application.discovery_pressure import DiscoveryPressure
    # R-dp2: `ledger` is the same host ledger reading the Fleet runner admits against (FleetLauncher.budget_exhausted) and
    # `census` coordination's census read; the composition supplies both (S10 carry: the M7 callers wire them).
    return DiscoveryPressure(store, packaged_policy(), observer, ledger=ledger, census=census)
