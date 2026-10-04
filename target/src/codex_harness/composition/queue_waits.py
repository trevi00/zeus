"""The composition wrappers that emit `operations.queue_item_waited` for the frontdesk and research-dispatch claims (INV-OBSERVATION-001).

Layer: composition
Owns: queue_wait_seconds, emit_queue_wait, ObservedDesk, observed_research_program
Does not own: the claims (intake.application.frontdesk.FrontDesk.claim_next, research.application.research_program.ResearchProgram._claim_investigation, both S8-pinned and unchanged), the observer builders (composition.observation) and the catalog
Entry points: ObservedDesk, observed_research_program
Contracts: INV-OBSERVATION-001

S10 F2-B (FLEET-REBUILD-S10-ACCEPT F2, DESIGN-s10 §17c, R-a54 (2)): the S8 pins fix the two owners, so the instrumentation is a wrapper built by composition only, around an observer composition already holds. Each wrapper calls the pinned method unchanged and
reports AFTER it returned (the claim's transaction has committed), so a refused or rolled-back claim emits nothing and the claim result is the owner's own.

`wait_seconds` is the claim time minus the row's own enqueue time, both read from the row: the desk request's `created_at` and `dispatched_at` (set by `claim_next`); the research candidate's `created_at` (when the program first held the investigation
as an eligible candidate) and the claim's `now`. A row without a parseable timezone-aware enqueue or claim time, or one enqueued after the claim, emits nothing: no guessed wait. Imports sit inside the functions, so importing this module stays light.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from functools import lru_cache


def queue_wait_seconds(enqueued, claimed):
    """Seconds between two timezone-aware ISO instants, or None when either is not one or the order is reversed."""
    try:
        start, end = datetime.fromisoformat(enqueued), datetime.fromisoformat(claimed)
    except (TypeError, ValueError):
        return None
    if start.tzinfo is None or end.tzinfo is None:
        return None
    wait = (end - start).total_seconds()
    return wait if wait >= 0 else None


def emit_queue_wait(observer, queue: str, item_id, enqueued, claimed) -> None:
    wait = queue_wait_seconds(enqueued, claimed)
    if observer is None or wait is None:
        return
    observer.emit("operations.queue_item_waited", "observed", attributes={
        "queue": queue, "item_ref": "sha256:" + hashlib.sha256(str(item_id).encode("utf-8")).hexdigest(),
        "wait_seconds": wait, "outcome": "started"})


class ObservedDesk:
    """The front-desk queue the `DeskRunner` claims from, with the claim reported: every other attribute is the desk's own."""

    def __init__(self, desk, observer):
        self._desk, self._observer = desk, observer

    def __getattr__(self, name):
        return getattr(self._desk, name)

    def claim_next(self):
        row = self._desk.claim_next()
        if row is not None:
            emit_queue_wait(self._observer, "frontdesk", row.get("id"), row.get("created_at"), row.get("dispatched_at"))
        return row


@lru_cache(maxsize=1)
def _observed_program_class():
    from codex_harness.research.application.research_program import ResearchProgram

    class ObservedResearchProgram(ResearchProgram):
        """`ResearchProgram` whose investigation claims are reported once `record_collection` has committed them."""

        def __init__(self, *args, observer=None, **kwargs):
            super().__init__(*args, **kwargs)
            self._observer, self._claims = observer, []

        def _claim_investigation(self, tx, chosen, cycle, now):
            dispatch = super()._claim_investigation(tx, chosen, cycle, now)
            self._claims.append((chosen["investigation"], chosen.get("created_at"), now))
            return dispatch

        def record_collection(self, *args, **kwargs):
            self._claims = []
            try:
                result = super().record_collection(*args, **kwargs)
                claims = self._claims
            finally:
                self._claims = []
            for investigation, enqueued, claimed in claims:
                emit_queue_wait(self._observer, "research_dispatch", investigation, enqueued, claimed)
            return result

    return ObservedResearchProgram


def observed_research_program(store, observer, **ports):
    """`ResearchProgram(store, **ports)` reporting its investigation claims to `observer`."""
    return _observed_program_class()(store, observer=observer, **ports)
