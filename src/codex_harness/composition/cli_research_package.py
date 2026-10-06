"""The `zeus research-package` composition: the package store, the exemption writers and the accept-and-resolve use case.

Layer: composition
Owns: packages, accept_and_resolve, status
Does not own: the argument shape and the command bodies (entry.cli.research_package), the package store and the
    admission policy (research.application), the holding record (coordination.application.research_admission)
Entry points: packages, accept_and_resolve, status
Contracts: INV-RESEARCH-001, INV-RESEARCH-004 (addendum A1 v2 RF-RT)

A declared target addition (DESIGN-s10 §14 G20-D6; RF-RT has no M7 counterpart). research may not import coordination,
so the combination that accepts a package AND releases the holds it answers is composed here: in ONE store transaction
the package is accepted and every holding `research_admissions` record whose task's research key equals the package
key is resolved, naming the decision ref (S5 `resolve`).
"""
from codex_harness.kernel.errors import ContractError

OPERATOR = "operator"  # M7 CLIs carry no identity (G20-D4 revision)


def packages(service):
    """The package store of `service` (it joins the caller's transaction)."""
    from codex_harness.research.application.research_packages import ResearchPackages
    return ResearchPackages()


def accept_and_resolve(service, key: str, version: int, decision_ref: str, *, clock=None) -> dict:
    """Accept `(key, version)` and resolve the holding admissions of tasks whose research key is `key`, atomically."""
    from codex_harness.coordination.application.research_admission import (
        BUCKET,
        HOLDING,
        PersistedResearchAdmission,
    )
    from codex_harness.research.application.research_packages import ResearchPackages
    from codex_harness.research.domain.research_package import research_key
    owner, admission = ResearchPackages(clock=clock), PersistedResearchAdmission(clock=clock)
    resolved = []
    with service.store.transaction() as tx:
        row = owner.accept(tx, key, version, decision_ref)
        for record in sorted(tx.scan(BUCKET), key=lambda held: held["id"]):
            if record.get("state") != HOLDING:
                continue
            task = tx.get("tasks", record["task_id"])
            try:
                same = task is not None and research_key(task) == key
            except ContractError:
                same = False
            if same:
                admission.resolve(tx, record["task_id"], record["action"], resolution_ref=decision_ref, actor=OPERATOR)
                resolved.append({"task_id": record["task_id"], "action": record["action"]})
    return {"key": row["key"], "version": row["version"], "status": row["status"], "decision_ref": row["decision_ref"],
            "resolved": resolved}


def status(service, key: str) -> dict:
    """Read only: the versions of `key`, the current package and the active exemption."""
    owner = packages(service)
    with service.store.transaction() as tx:
        versions = owner.versions(tx, key)
        current = owner.current(tx, key)
        exemption = owner.active_exemption(tx, key)
    return {"key": key,
            "versions": [{"version": row["version"], "status": row["status"], "decision_ref": row["decision_ref"],
                          "sources": len(row["sources"])} for row in versions],
            "current": None if current is None else {"version": current["version"], "status": current["status"]},
            "exemption": None if exemption is None else {"class": exemption["class"], "reason": exemption["reason"],
                                                         "recorded_by": exemption["recorded_by"],
                                                         "recorded_at": exemption["recorded_at"]}}
