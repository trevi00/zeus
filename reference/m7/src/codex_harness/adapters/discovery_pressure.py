"""Packaged policy and the evaluator factory for proactive discovery pressure (INV-DISCOVERY-PRESSURE-001).

The thresholds are the packaged document's (3 and 1, labelled `suggested_unconfirmed`: the user's initial
suggestion, not a confirmed constant); no caller supplies a numeric default."""
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


def pressure(store, observer):
    """The evaluator over THIS process's store. In a lane process that store has no Fleet registry, so
    pressure reads as unregistered and holds proactive discovery: a lane store never stands in for the
    control store's pressure."""
    from codex_harness.adapters.call_budget import CallBudget
    from codex_harness.application.discovery_pressure import DiscoveryPressure
    # The same host ledger reading the Fleet runner admits against (FleetLauncher.budget_exhausted).
    return DiscoveryPressure(store, packaged_policy(), observer, ledger=lambda: CallBudget().counts())
