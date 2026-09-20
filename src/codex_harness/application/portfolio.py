"""Operating portfolio: owner goals, job bindings, acceptances and failure candidates.

docs/zeus/operations/operating-portfolio-001/SPEC.md. Three buckets over the existing store:
`portfolio_bindings` (one immutable row per Fleet job naming the goal criterion it serves),
`portfolio_acceptances` (the owner's explicit criterion completion record, the only source of an
`accepted` criterion) and `portfolio_investigations` (durable candidates built from repeated
terminal failures). Definitions are owner-authored data passed in by the adapter: nothing here
reads a file, launches a process or talks to a provider.

A candidate is a coarse triage family - the same status and reason code observed on two or more
distinct jobs - never a confirmed cause, a verified incident or an executed fix. Reconciliation
groups and counts; it never rewrites a Fleet job, retries anything or resets an owner disposition.
Acceptance is never inferred from a job status, and an unknown or missing value never becomes
success: it stays unknown and is counted as such.
"""
from __future__ import annotations

from codex_harness.application.fleet import BUCKET_JOBS
from codex_harness.domain.fleet import FAILED, REJECTED, safe_code
from codex_harness.domain.model import ContractError, digest, utcnow
from codex_harness.domain.operation import safe_relative_path

DEFINITIONS_SCHEMA = "urn:zeus:portfolio-definitions:1"
STATUS_SCHEMA = "urn:zeus:portfolio-status:1"

BUCKET_BINDINGS = "portfolio_bindings"
BUCKET_ACCEPTANCES = "portfolio_acceptances"
BUCKET_INVESTIGATIONS = "portfolio_investigations"

PENDING, ACCEPTED_CRITERION = "pending", "accepted"
RESEARCH_REQUIRED, RESEARCHED, DEFERRED = "research_required", "researched", "deferred"
DISPOSITIONS = frozenset({RESEARCHED, DEFERRED})
# Only definite terminal failures of independent work form a family; `unknown` keeps its existing
# Fleet reconciliation semantics (uncertain, never taken over here) and `accepted`, `exhausted`,
# `dispatching` and `queued` are not failures.
FAILURE_STATUSES = frozenset({FAILED, REJECTED})
UNCLASSIFIED = "unknown"   # the code `Fleet.finalize` records when no safe reason was observed
FAMILY_MINIMUM = 2

SAMPLE = 50
MAX_PROJECTS, MAX_CRITERIA = 16, 16
MAX_ID, MAX_TITLE, MAX_TEXT, MAX_REF, MAX_REFS = 64, 120, 600, 200, 10


class PortfolioRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("portfolio refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _identifier(value) -> bool:
    return (type(value) is str and 0 < len(value) <= MAX_ID
            and all(c.isalnum() or c in "._-" for c in value) and value[0].isalnum())


def _text(value, limit: int) -> bool:
    return (type(value) is str and 0 < len(value.strip()) <= limit
            and all(ord(c) >= 32 or c == "\n" for c in value))


def _fields(document, expected, field: str) -> None:
    if not isinstance(document, dict) or set(document) != expected:
        raise PortfolioRefused("definitions_invalid", field)


def validate_definitions(document) -> dict:
    """The full owner-authored `urn:zeus:portfolio-definitions:1` shape. Refusals carry the field
    name only, never the offending value. Definitions declare intent: they assert no completion."""
    _fields(document, {"schema", "projects"}, "definitions")
    if document["schema"] != DEFINITIONS_SCHEMA:
        raise PortfolioRefused("definitions_invalid", "schema")
    projects = document["projects"]
    if not isinstance(projects, list) or not 1 <= len(projects) <= MAX_PROJECTS:
        raise PortfolioRefused("definitions_invalid", "projects")
    output = []
    for project in projects:
        _fields(project, {"id", "title", "outcome", "source_ref", "criteria"}, "projects[]")
        if not _identifier(project["id"]):
            raise PortfolioRefused("definitions_invalid", "projects[].id")
        if not _text(project["title"], MAX_TITLE):
            raise PortfolioRefused("definitions_invalid", "projects[].title")
        if not _text(project["outcome"], MAX_TEXT):
            raise PortfolioRefused("definitions_invalid", "projects[].outcome")
        if not safe_relative_path(project["source_ref"]):
            raise PortfolioRefused("definitions_invalid", "projects[].source_ref")
        criteria = project["criteria"]
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= MAX_CRITERIA:
            raise PortfolioRefused("definitions_invalid", "projects[].criteria")
        for criterion in criteria:
            _fields(criterion, {"id", "text"}, "projects[].criteria[]")
            if not _identifier(criterion["id"]):
                raise PortfolioRefused("definitions_invalid", "projects[].criteria[].id")
            if not _text(criterion["text"], MAX_TEXT):
                raise PortfolioRefused("definitions_invalid", "projects[].criteria[].text")
        if len({c["id"] for c in criteria}) != len(criteria):
            raise PortfolioRefused("definitions_duplicate", "projects[].criteria[].id")
        output.append({"id": project["id"], "title": project["title"], "outcome": project["outcome"],
                       "source_ref": project["source_ref"],
                       "criteria": [{"id": c["id"], "text": c["text"]} for c in criteria]})
    if len({p["id"] for p in output}) != len(output):
        raise PortfolioRefused("definitions_duplicate", "projects[].id")
    return {"schema": DEFINITIONS_SCHEMA, "projects": output}


def validate_evidence(refs) -> list[str]:
    """Nonempty, bounded, distinct opaque owner references. The content is never parsed, fetched
    or verified here: recording a reference is not evidence that anything was checked."""
    if not isinstance(refs, list) or not 1 <= len(refs) <= MAX_REFS:
        raise PortfolioRefused("evidence_invalid", "evidence_refs")
    for ref in refs:
        if not _text(ref, MAX_REF) or "\n" in ref:
            raise PortfolioRefused("evidence_invalid", "evidence_refs[]")
    if len(set(refs)) != len(refs):
        raise PortfolioRefused("evidence_invalid", "evidence_refs[]")
    return list(refs)


def family_id(status: str, reason_code: str) -> str:
    """Deterministic identity of one triage family, stable across processes and restarts."""
    return digest({"family_status": status, "reason_code": reason_code})


def classified_failure(job: dict) -> tuple[str, str] | None:
    """The family of one job, or None when it is not a classifiable terminal failure.

    A reason that is absent, not already a fixed safe code, or exactly `unknown` is excluded and
    counted instead: `Fleet.finalize` stores `unknown` precisely when the reason was missing or
    unsafe, so grouping those rows would invent a shared symptom that was never observed.
    """
    status, reason = job.get("status"), job.get("reason_code")
    if status not in FAILURE_STATUSES:
        return None
    if type(reason) is not str or not reason or reason == UNCLASSIFIED or safe_code(reason) != reason:
        return None
    return status, reason


def failure_families(jobs: list[dict]) -> tuple[dict, int]:
    """(family key -> sorted distinct job ids, unclassified failure count) over ALL given rows."""
    families: dict[tuple[str, str], set] = {}
    unclassified = 0
    for job in jobs:
        job_id = job.get("id")
        if type(job_id) is not str or not job_id:
            continue
        family = classified_failure(job)
        if family is None:
            if job.get("status") in FAILURE_STATUSES:
                unclassified += 1   # a failure whose reason is missing or not a fixed code
            continue
        families.setdefault(family, set()).add(job_id)
    return families, unclassified


def reconcile(store, clock=utcnow) -> dict:
    """One serialized store transaction over ALL `fleet_jobs`: group terminal failed/rejected jobs
    with a safe reason code by (status, reason_code) and keep every family of at least two distinct
    jobs as a durable candidate. No Fleet row, manifest, task row or owner disposition is touched,
    no raw error, prompt, command or credential is stored, and nothing is retried. Definitions are
    not needed, so a runner can call this without them.

    The returned summary counts what was observed; it asserts no cause.
    """
    now = clock()
    with store.transaction() as tx:
        jobs = tx.scan(BUCKET_JOBS)
        families, unclassified = failure_families(jobs)
        created, updated, candidates = 0, 0, []
        for (status, reason), job_ids in sorted(families.items()):
            if len(job_ids) < FAMILY_MINIMUM:
                continue
            key = family_id(status, reason)
            candidates.append(key)
            row = tx.get(BUCKET_INVESTIGATIONS, key)
            if row is None:
                tx.put(BUCKET_INVESTIGATIONS, key, {
                    "id": key, "family_status": status, "reason_code": reason,
                    "state": RESEARCH_REQUIRED, "job_ids": sorted(job_ids), "count": len(job_ids),
                    "evidence_refs": [], "decided_at": None, "created_at": now, "updated_at": now})
                created += 1
                continue
            merged = sorted(set(row.get("job_ids", [])) | job_ids)
            if merged == list(row.get("job_ids", [])):
                continue
            # A disposition already recorded by the owner survives: only the observed membership
            # and its count move, so new failures stay visible without reopening the decision.
            row.update(job_ids=merged, count=len(merged), updated_at=now)
            tx.put(BUCKET_INVESTIGATIONS, key, row)
            updated += 1
    return {"reconciled": True, "scanned": len(jobs), "families": len(families),
            "candidates": candidates, "created": created, "updated": updated,
            "unclassified_failures": unclassified, "at": now}


def job_entry(job: dict, criterion_id: str) -> dict:
    """The bounded wire shape of one bound job: identities, lane, state and a fixed code only."""
    reason = job.get("reason_code")
    return {"id": job["id"], "criterion_id": criterion_id, "lane": job.get("lane"),
            "status": job.get("status"),
            "reason_code": None if reason is None else safe_code(reason),
            "updated_at": job.get("updated_at")}


def _latest(rows: list[dict], key) -> tuple[list[dict], bool]:
    return sorted(rows, key=key)[-SAMPLE:], len(rows) > SAMPLE


def status_projection(definitions: dict, jobs: list[dict], bindings: list[dict],
                      acceptances: list[dict], investigations: list[dict]) -> dict:
    """`urn:zeus:portfolio-status:1`: every defined goal appears, bound work is sampled with the
    complete counts beside it, and criterion status comes ONLY from explicit owner acceptance
    records. No manifest, objective, filesystem path, credential or raw error is projected."""
    rows = {job["id"]: job for job in jobs if type(job.get("id")) is str}
    accepted = {(row["project_id"], row["criterion_id"]): row for row in acceptances}
    defined = {(p["id"], c["id"]) for p in definitions["projects"] for c in p["criteria"]}
    bound: dict[str, list] = {}
    bound_ids = set()
    for binding in bindings:
        job = rows.get(binding.get("job_id"))
        target = (binding.get("project_id"), binding.get("criterion_id"))
        if job is None or target not in defined:
            # The binding names a job this store no longer has, or a criterion these definitions
            # no longer define: the job is not shown under a goal and stays counted as unbound.
            continue
        bound_ids.add(job["id"])
        bound.setdefault(binding["project_id"], []).append(job_entry(job, binding["criterion_id"]))
    projects = []
    for project in definitions["projects"]:
        entries = bound.get(project["id"], [])
        sample, truncated = _latest(entries, lambda e: (e["updated_at"] or "", e["id"]))
        criteria = []
        for criterion in project["criteria"]:
            record = accepted.get((project["id"], criterion["id"]))
            criteria.append({"id": criterion["id"], "text": criterion["text"],
                             "status": PENDING if record is None else ACCEPTED_CRITERION,
                             "evidence_refs": list(record["evidence_refs"]) if record else []})
        projects.append({"id": project["id"], "title": project["title"], "outcome": project["outcome"],
                         "source_ref": project["source_ref"], "criteria": criteria, "jobs": sample,
                         "counts": {"criteria_total": len(criteria),
                                    "criteria_accepted": sum(c["status"] == ACCEPTED_CRITERION for c in criteria),
                                    "jobs_total": len(entries)},
                         "jobs_truncated": truncated})
    queue, queue_truncated = _latest(investigations, lambda r: (r.get("updated_at") or "", r["id"]))
    candidates = [{"id": row["id"], "family_status": row["family_status"], "reason_code": row["reason_code"],
                   "state": row["state"], "count": row["count"],
                   # A bounded sample of the family's members; `count` is the complete number.
                   "job_ids": sorted(row.get("job_ids", []))[-SAMPLE:],
                   "evidence_refs": list(row.get("evidence_refs", [])),
                   "updated_at": row.get("updated_at")} for row in queue]
    _, unclassified = failure_families(jobs)
    return {"schema": STATUS_SCHEMA, "definition_sha256": digest(definitions), "projects": projects,
            "investigations": candidates, "investigations_truncated": queue_truncated,
            "unbound_jobs": len(rows) - len(bound_ids), "unclassified_failures": unclassified}


class Portfolio:
    """Owner-only operations over validated definitions; every method is one store transaction."""

    def __init__(self, store, definitions, clock=utcnow):
        self.store, self.clock = store, clock
        self.definitions = validate_definitions(definitions)
        self.definition_sha256 = digest(self.definitions)

    def _target(self, project_id: str, criterion_id: str) -> None:
        project = next((p for p in self.definitions["projects"] if p["id"] == project_id), None)
        if project is None:
            raise PortfolioRefused("project_unknown", "project_id")
        if not any(c["id"] == criterion_id for c in project["criteria"]):
            raise PortfolioRefused("criterion_unknown", "criterion_id")

    # ----- owner records ------------------------------------------------------------------
    def bind(self, job_id: str, project_id: str, criterion_id: str) -> dict:
        """Bind an EXISTING Fleet job to a defined criterion. The binding is immutable and keyed by
        the job: an identical replay is cached, any other target is refused. Nothing is inferred
        from a title, objective or path, and no Fleet manifest, job row or task row is modified."""
        self._target(project_id, criterion_id)
        if type(job_id) is not str or not job_id:
            raise PortfolioRefused("binding_invalid", "job_id")
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_BINDINGS, job_id)
            if old is not None:
                if (old["project_id"], old["criterion_id"]) != (project_id, criterion_id):
                    raise PortfolioRefused("binding_conflict")
                return {"bound": True, "cached": True, "binding": dict(old)}
            if tx.get(BUCKET_JOBS, job_id) is None:
                raise PortfolioRefused("job_unknown", "job_id")
            row = {"id": job_id, "job_id": job_id, "project_id": project_id,
                   "criterion_id": criterion_id, "recorded_by": "owner", "created_at": self.clock()}
            tx.put(BUCKET_BINDINGS, job_id, row)
        return {"bound": True, "cached": False, "binding": dict(row)}

    def accept(self, project_id: str, criterion_id: str, evidence_refs) -> dict:
        """The trusted owner's explicit criterion completion record: the SOLE source of an accepted
        criterion, never inferred from a job status. Immutable; the identical replay is cached and
        any different record is refused."""
        self._target(project_id, criterion_id)
        refs = validate_evidence(evidence_refs)
        key = project_id + ":" + criterion_id
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_ACCEPTANCES, key)
            if old is not None:
                if old["evidence_refs"] != refs:
                    raise PortfolioRefused("acceptance_conflict")
                return {"accepted": True, "cached": True, "acceptance": dict(old)}
            row = {"id": key, "project_id": project_id, "criterion_id": criterion_id,
                   "evidence_refs": refs, "authority": "owner_recorded", "recorded_by": "owner",
                   "created_at": self.clock()}
            tx.put(BUCKET_ACCEPTANCES, key, row)
        return {"accepted": True, "cached": False, "acceptance": dict(row)}

    def disposition(self, candidate_id: str, state: str, evidence_refs) -> dict:
        """The owner's first decision on a candidate: `researched` or `deferred`, with mandatory
        references. Immutable - the identical replay is cached, a different decision refused - and
        it promotes no root cause: a disposition records that the owner looked, nothing more."""
        if state not in DISPOSITIONS:
            raise PortfolioRefused("disposition_invalid", "state")
        refs = validate_evidence(evidence_refs)
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INVESTIGATIONS, candidate_id)
            if row is None:
                raise PortfolioRefused("candidate_unknown", "candidate_id")
            if row["state"] != RESEARCH_REQUIRED:
                if row["state"] != state or row["evidence_refs"] != refs:
                    raise PortfolioRefused("disposition_conflict")
                return {"decided": True, "cached": True, "candidate": dict(row)}
            now = self.clock()
            row.update(state=state, evidence_refs=refs, decided_at=now, updated_at=now)
            tx.put(BUCKET_INVESTIGATIONS, candidate_id, row)
        return {"decided": True, "cached": False, "candidate": dict(row)}

    def reconcile(self) -> dict:
        """Definitions play no part in grouping failures; this is the standalone function."""
        return reconcile(self.store, self.clock)

    # ----- read-only ----------------------------------------------------------------------
    def status(self) -> dict:
        """The complete bounded projection. Read-only: it never reconciles, writes or repairs, and
        a store failure propagates so the collector reports `unavailable` instead of zero."""
        with self.store.transaction() as tx:
            jobs = tx.scan(BUCKET_JOBS)
            bindings = tx.scan(BUCKET_BINDINGS)
            acceptances = tx.scan(BUCKET_ACCEPTANCES)
            investigations = tx.scan(BUCKET_INVESTIGATIONS)
        return status_projection(self.definitions, jobs, bindings, acceptances, investigations)


__all__ = ["BUCKET_ACCEPTANCES", "BUCKET_BINDINGS", "BUCKET_INVESTIGATIONS", "DEFERRED",
           "RESEARCHED", "RESEARCH_REQUIRED", "STATUS_SCHEMA", "Portfolio", "PortfolioRefused",
           "family_id", "reconcile", "status_projection", "validate_definitions"]
