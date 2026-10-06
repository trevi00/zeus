"""Portfolio lineage: a continuation successor inherits exactly its origin's project binding, inside the caller's unit.

Layer: application
Context: intake
Owns: bucket portfolio_bindings (the lineage rows; S8 moves the rest of the Portfolio owner here)
Does not own: the lineage proof (coordination's persisted successor intent), the Fleet jobs (read only)
Entry points: PortfolioLineage.inherit, inherit_binding
Contracts: INV-CONTINUATION-001

S6 moved ahead verbatim from M7 `application/portfolio.py` (DESIGN-s6 §5): `inherit_binding` joins the caller's
open transaction (never a nested one). `PortfolioLineage` is the structural implementation of coordination's
`PortfolioLineage` port.
"""
from __future__ import annotations

from codex_harness.intake.domain.portfolio import PortfolioRefused

BUCKET_BINDINGS = "portfolio_bindings"
BUCKET_JOBS = "fleet_jobs"  # coordination's Fleet jobs, read only
LINEAGE_AUTHORITY = ("present ownership inherited through verified continuation lineage; not historical "
                     "capture membership and not criterion acceptance")


def inherit_binding(tx, job_id: str, origin_job_id: str, lineage: dict, now: str) -> dict | None:
    """Bind `job_id` to exactly the project and criterion its continuation origin is bound to, inside
    the CALLER's open transaction (never a nested one; SPEC "Research coverage ownership").

    The caller has already proven the lineage (the persisted successor intent and both Fleet rows);
    nothing is inferred from a title, objective or path. An unbound origin returns None: legacy
    unbound work stays unbound and no project is guessed. An existing binding of the same target
    replays (`cached`), any other target is `binding_conflict` and nothing is overwritten. The row is
    immutable like an owner binding and additionally names its lineage."""
    origin = tx.get(BUCKET_BINDINGS, origin_job_id)
    if origin is None:
        return None
    target = (origin["project_id"], origin["criterion_id"])
    old = tx.get(BUCKET_BINDINGS, job_id)
    if old is not None:
        if (old["project_id"], old["criterion_id"]) != target:
            raise PortfolioRefused("binding_conflict")
        return {"bound": True, "cached": True, "binding": dict(old)}
    if tx.get(BUCKET_JOBS, job_id) is None:
        raise PortfolioRefused("job_unknown", "job_id")
    row = {"id": job_id, "job_id": job_id, "project_id": target[0], "criterion_id": target[1],
           "recorded_by": "continuation_lineage", "lineage": {"origin_job": origin_job_id, **lineage},
           "authority": LINEAGE_AUTHORITY, "created_at": now}
    tx.put(BUCKET_BINDINGS, job_id, row)
    return {"bound": True, "cached": False, "binding": dict(row)}


class PortfolioLineage:
    """The PortfolioLineage port: intake's lineage owner operation, called inside the caller's transaction."""

    def inherit(self, tx, job_id: str, origin_job_id: str, lineage: dict, now: str) -> dict | None:
        return inherit_binding(tx, job_id, origin_job_id, lineage, now)
