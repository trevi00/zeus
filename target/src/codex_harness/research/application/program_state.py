"""Research program state: the owner-action research launch resumes a paused program (M7 `ResearchProgram.resume`).

Layer: application
Context: research
Owns: bucket research_programs (the paused -> active transition here; S8 moves the rest of ResearchProgram)
Does not own: the owner action that asks for it (coordination.application.owner_actions.research_dispatch)
Entry points: ProgramState.resume
Contracts: INV-OWNER-ACTIONS-001

S6 moved ahead verbatim (DESIGN-s6 §5): `resume` and `_row` of M7 `ResearchProgram`, one unit each as in M7, the
structural implementation of coordination's `ResearchPrograms` port.
"""
from __future__ import annotations

from codex_harness.kernel.ids import utcnow
from codex_harness.research.domain.research_program import ACTIVE, BLOCKED, COMPLETED, PAUSED, ProgramRefused

BUCKET_PROGRAMS = "research_programs"


class ProgramState:
    """The research program row's resume (M7 `ResearchProgram`, resume part)."""

    def __init__(self, store, clock=utcnow):
        self.store, self.clock = store, clock

    def _row(self, tx, program_id: str) -> dict:
        row = tx.get(BUCKET_PROGRAMS, program_id)
        if row is None:
            raise ProgramRefused("unknown_program")
        return row

    def resume(self, program_id: str) -> dict:
        """Paused -> active only. Completed stays completed; blocked needs a new authorized program
        (no blind repair); the counters are untouched either way."""
        with self.store.transaction() as tx:
            row = self._row(tx, program_id)
            if row["state"] in {COMPLETED, BLOCKED}:
                raise ProgramRefused("program_" + row["state"])
            if row["state"] == PAUSED:
                row.update(state=ACTIVE, updated_at=self.clock())
                tx.put(BUCKET_PROGRAMS, program_id, row)
            return {"id": program_id, "state": row["state"], "active_cycle": row["active_cycle"]}
