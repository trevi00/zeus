"""The per-attempt outcome record of one execution row (INV-METRIC-001).

Layer: domain
Context: coordination
Owns: attempt_outcome (M7 `Workflow._attempt_outcome`, unchanged)
Does not own: the row's other fields or its persistence (the workflow)
Entry points: attempt_outcome
Contracts: INV-METRIC-001

Moved out of the Workflow class so execution_time's deadline containment records the outcome without importing
the workflow: M7 had the import cycle execution_time <-> workflow (REBUILD-DESIGN-v2 §2.2); the target has none.
`Workflow._attempt_outcome` stays as the same function.
"""

from __future__ import annotations


def attempt_outcome(task, status, at, error=None):
    # INV-METRIC-001: retain failures across retries; never invent legacy outcomes.
    if task['attempt'] and not any(r['attempt'] == task['attempt']
                                  for r in task.get('attempt_outcomes', [])):
        task.setdefault('attempt_outcomes', []).append(
            {'attempt': task['attempt'], 'status': status, 'at': at, 'error': error})
