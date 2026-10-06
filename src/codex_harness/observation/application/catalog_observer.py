"""The catalog-checking Observer decorator (X1, DESIGN-s9-X §1.1; OBSERVABILITY-COVERAGE-20261002).

Layer: application
Context: observation
Owns: `CatalogCheckingObserver`, which refuses a catalog event's attributes (a closed-enum value outside the
    catalog, a non-opaque id, an undeclared attribute) BEFORE the wrapped Observer builds the event
Does not own: the Observer (`observation.application.observations`, pinned verbatim by S9 batch L2-B4), the catalog
    and its check (`observation.domain.event_catalog`), or the composition that wires it (S10)
Entry points: CatalogCheckingObserver, CatalogCheckingObserver.emit, CatalogCheckingObserver.audit
Contracts: INV-OBSERVATION-001, OBSERVABILITY-COVERAGE-20261002

`emit` is the diagnostic path and never raises: a refused catalog event is counted and recorded by the wrapped
Observer's own refusal path and nothing is spooled. `audit` is the mandatory path and raises the refusal, like the
Observer. An event type outside the catalog, and every other attribute, forwards unchanged.
"""
from __future__ import annotations

import functools

from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain.event_catalog import check_catalog_attributes, load_catalog


@functools.cache
def _catalog_event_types() -> frozenset:
    return frozenset(load_catalog()["events"])


class CatalogCheckingObserver:
    """Wraps an Observer; checks catalog events against the catalog first, delegates everything else."""

    def __init__(self, observer):
        self._observer = observer

    def __getattr__(self, name):
        return getattr(self._observer, name)

    @staticmethod
    def _check(event_type, fields):
        if event_type in _catalog_event_types():
            check_catalog_attributes(event_type, fields.get("attributes") or {})

    def emit(self, event_type, outcome, **fields):
        try:
            self._check(event_type, fields)
        except ContractError as exc:
            self._observer._refused(event_type, exc)
            return None
        return self._observer.emit(event_type, outcome, **fields)

    def audit(self, tx, event_type, outcome, **fields):
        self._check(event_type, fields)
        return self._observer.audit(tx, event_type, outcome, **fields)
