"""Portfolio adapter: the packaged owner definitions and the Fleet reconciliation callable.

Layer: adapters
Context: intake
Owns: `packaged_definitions` (the owner-written definition resource, unvalidated), `portfolio` (the Portfolio over a store) and `portfolio_reconciler` (the bounded per-tick callable)
Does not own: the validation and every owner operation (intake.application.portfolio)
Entry points: packaged_definitions, portfolio, portfolio_reconciler, DEFINITIONS
Contracts: INV-CONTINUATION-001

Moved from M7 `adapters/portfolio.py` (SOURCE e38aa722) through named rule R-p5 (DESIGN-s8, A/evidence/rebuild/s8/portfolio-move/transcribe.py): only the `Portfolio, reconcile` import home and this header differ. M7 module docstring:

docs/zeus/operations/operating-portfolio-001/SPEC.md. The definitions are owner-authored data in
`codex_harness.resources`; only this adapter reads them, and the application validates them. There
is no web writer and no CLI here: binding, acceptance and disposition are trusted owner calls.
"""
from __future__ import annotations

import json
from importlib.resources import files

from codex_harness.intake.application.portfolio import Portfolio, reconcile

DEFINITIONS = "operating-portfolio-v1.json"


def packaged_definitions(name: str = DEFINITIONS) -> dict:
    """The owner-written definition resource, unvalidated: `Portfolio` validates it."""
    return json.loads(files("codex_harness.resources").joinpath(name).read_text("utf-8"))


def portfolio(store, definitions: dict | None = None) -> Portfolio:
    return Portfolio(store, packaged_definitions() if definitions is None else definitions)


def portfolio_reconciler(store):
    """The bounded per-tick callable for `FleetRunner(..., reconcile=...)`.

    Grouping failures needs no definitions, so this stays independent of the resource file and of
    admission: it opens its own transaction and returns a counted summary, never a cause.
    """
    return lambda: reconcile(store)


__all__ = ["DEFINITIONS", "packaged_definitions", "portfolio", "portfolio_reconciler"]
