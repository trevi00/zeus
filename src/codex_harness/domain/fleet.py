"""Fleet definitions, job admission rules and the read-only team projection (INV-FLEET-001).

A fleet is one host-authored configuration (`urn:zeus:fleet:1`): up to four lanes, each with its
own repository, PostgreSQL schema, Redis namespace and runtime root, a fixed concurrency cap and
the machine call ceilings every job must carry. Jobs are frozen `urn:zeus:operation` manifests
bound to one lane. Everything here is pure policy over dictionaries: no store, process, git or
provider access. Values are never placed in error messages; the field name is.
"""
from __future__ import annotations

import os
import re

from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import safe_relative_path
from codex_harness.domain.usage_policy import NUMERIC_FIELDS, UsagePolicyError, accounting_mode
from codex_harness.domain.usage_policy import validate_budget as policy_budget
from codex_harness.domain.usage_policy import validate_grant as policy_grant

CONFIG_SCHEMA = "urn:zeus:fleet:1"
STATUS_SCHEMA = "urn:zeus:fleet-status:1"
CONFIG_FIELDS = {"schema", "id", "max_parallel", "budget", "lanes"}
BUDGET_FIELDS = set(NUMERIC_FIELDS)  # the legacy finite shape; `mode` is optional (usage_policy)
LANE_FIELDS = {"id", "team", "repository", "schema", "redis_namespace", "runtime"}
MAX_LANES = 4
JOB_SAMPLE = 100
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# A PostgreSQL identifier that never needs quoting and can never name the public schema.
SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
RESERVED_SCHEMAS = {"public", "information_schema"}
SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
GLOB = frozenset("*?[]{}")

QUEUED, DISPATCHING = "queued", "dispatching"
ACCEPTED, REJECTED, FAILED, EXHAUSTED, UNKNOWN = "accepted", "rejected", "failed", "exhausted", "unknown"
TERMINAL = frozenset({ACCEPTED, REJECTED, FAILED, EXHAUSTED, UNKNOWN})
# States that hold the lane, a capacity slot and the path exclusion: a dispatching job (from the
# durable claim, before the process exists, until its outcome is recorded) and an unknown outcome,
# whose external effects are uncertain and are never taken over automatically.
RESERVING = frozenset({DISPATCHING, UNKNOWN})
DEPENDENCY_BLOCKING = frozenset({REJECTED, FAILED, EXHAUSTED, UNKNOWN})


class FleetRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("fleet refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _integer(value) -> bool:
    return type(value) is int


def _token(value) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


def _fields(document, expected, name):
    if not isinstance(document, dict):
        raise FleetRefused("config_invalid", name)
    if set(document) != expected:
        raise FleetRefused("config_fields", name)


def normalize_path(value: str) -> str:
    """Conservative comparison form on both platforms: forward slashes, casefolded, no trailing
    separator. Two paths that differ only in case or separator are treated as the same path."""
    text = value.replace("\\", "/").casefold()
    while "//" in text:
        text = text.replace("//", "/")
    return text.rstrip("/") if len(text) > 1 else text


def nested(inner: str, outer: str) -> bool:
    """True when `inner` equals `outer` or lies below it (both already normalized)."""
    return inner == outer or inner.startswith(outer.rstrip("/") + "/")


def paths_conflict(left: str, right: str) -> bool:
    """Relative allowed paths conflict when equal or one is a directory prefix of the other."""
    a, b = normalize_path(left), normalize_path(right)
    return nested(a, b) or nested(b, a)


def conflicting_paths(mine, others) -> list[str]:
    return sorted({p for p in mine for q in others if paths_conflict(p, q)})


def absolute_resolved(value) -> bool:
    """An absolute path already in its normalized spelling: no `..`, `.` or trailing separator.
    Filesystem resolution (symlinks, existence) is the adapter's check, not grammar."""
    if type(value) is not str or not value or "\x00" in value or not os.path.isabs(value):
        return False
    if os.path.normpath(value) != value:
        return False
    return ".." not in value.replace("\\", "/").split("/")


def validate_budget(budget, name="budget") -> dict:
    """The shared usage policy decides the shape (finite legacy form or explicit subscription mode)."""
    try:
        return policy_budget(budget)
    except UsagePolicyError as exc:
        raise FleetRefused("config_" + exc.reason_code, name) from exc


def _lane(lane, index: int) -> dict:
    name = "lanes[" + str(index) + "]"
    _fields(lane, LANE_FIELDS, name)
    if not (_token(lane["id"]) and _token(lane["team"]) and _token(lane["redis_namespace"])):
        raise FleetRefused("config_invalid", name + ".id/team/redis_namespace")
    schema = lane["schema"]
    if (type(schema) is not str or SCHEMA_NAME.fullmatch(schema) is None or schema in RESERVED_SCHEMAS
            or schema.startswith("pg_")):
        raise FleetRefused("config_invalid", name + ".schema")
    for key in ("repository", "runtime"):
        if not absolute_resolved(lane[key]):
            raise FleetRefused("config_invalid", name + "." + key)
    return {k: lane[k] for k in sorted(LANE_FIELDS)}


def validate_config(document) -> dict:
    """Strict validation of the host fleet configuration; returns the canonical copy."""
    if not isinstance(document, dict) or document.get("schema") != CONFIG_SCHEMA:
        raise FleetRefused("config_schema")
    _fields(document, CONFIG_FIELDS, "root")
    if not _token(document["id"]):
        raise FleetRefused("config_invalid", "id")
    budget = validate_budget(document["budget"])
    lanes = document["lanes"]
    if not (isinstance(lanes, list) and 1 <= len(lanes) <= MAX_LANES):
        raise FleetRefused("config_invalid", "lanes")
    lanes = [_lane(lane, index) for index, lane in enumerate(lanes)]
    if not (_integer(document["max_parallel"]) and 1 <= document["max_parallel"] <= len(lanes)):
        raise FleetRefused("config_invalid", "max_parallel")
    for key in ("id", "schema", "redis_namespace"):
        if len({lane[key] for lane in lanes}) != len(lanes):
            raise FleetRefused("config_duplicate", "lanes[]." + key)
    runtimes = [normalize_path(lane["runtime"]) for lane in lanes]
    repositories = [normalize_path(lane["repository"]) for lane in lanes]
    for i, runtime in enumerate(runtimes):
        for j, other in enumerate(runtimes):
            if i != j and nested(runtime, other):
                raise FleetRefused("config_runtime_overlap", "lanes[" + str(i) + "].runtime")
        for repository in repositories:
            if nested(runtime, repository) or nested(repository, runtime):
                raise FleetRefused("config_runtime_in_repository", "lanes[" + str(i) + "].runtime")
    return {"schema": CONFIG_SCHEMA, "id": document["id"], "max_parallel": document["max_parallel"],
            "budget": budget, "lanes": lanes}


def config_digest(config: dict) -> str:
    return digest(config)


def effective_config(config: dict, control) -> dict:
    """The registered configuration with the effective ceilings: a granted budget in the control
    row replaces the registered one for new enqueue/admission; the registered config and its
    digest are never rewritten. A control row without a budget keeps the registered ceilings."""
    budget = control.get("budget") if isinstance(control, dict) else None
    if budget is None:
        return config
    return {**config, "budget": validate_budget(budget)}


def validate_grant(prior: dict, requested, expected_total) -> dict:
    """An explicit operator grant over the effective budget (compare-and-swap on the total): the
    stated expected total must be the current effective total, both numbers must be valid and
    monotonically nondecreasing, and either a number increases or the accounting mode changes
    with unchanged numbers (usage_policy.validate_grant). Never a reset."""
    new = validate_budget(requested)
    if not _integer(expected_total) or expected_total != prior["total"]:
        raise FleetRefused("budget_expected_mismatch", "expected_total")
    try:
        return policy_grant(prior, new)
    except UsagePolicyError as exc:
        raise FleetRefused("budget_decrease" if exc.reason_code == "decrease" else "budget_no_increase", "budget") from exc


def sanitized_config(config: dict) -> dict:
    """What may be displayed: identities and ceilings; never paths, schemas or namespaces."""
    return {"schema": config["schema"], "id": config["id"], "max_parallel": config["max_parallel"],
            "budget": dict(config["budget"]), "accounting_mode": accounting_mode(config["budget"]),
            "lanes": [{"id": lane["id"], "team": lane["team"]} for lane in config["lanes"]]}


def lane_of(config: dict, lane_id: str) -> dict:
    for lane in config["lanes"]:
        if lane["id"] == lane_id:
            return lane
    raise FleetRefused("lane_unknown")


def validate_job_manifest(manifest: dict, config: dict) -> None:
    """Fleet-specific rules over an already validated operation manifest: the job carries exactly
    the fleet ceiling (never its own budget) and only canonical, non-glob relative paths."""
    if manifest.get("budget") != config["budget"]:
        raise FleetRefused("budget_mismatch", "budget")
    paths = manifest["plan"]["allowed_paths"]
    for path in paths:
        if not safe_relative_path(path) or GLOB & set(path) or path != os.path.normpath(path).replace("\\", "/"):
            raise FleetRefused("path_not_canonical", "plan.allowed_paths")
    if len({normalize_path(p) for p in paths}) != len(paths):
        raise FleetRefused("path_not_canonical", "plan.allowed_paths")


# ----- owner delivery records (local-operations-desk-001) -----------------------------------
DELIVERY_SCHEMA = "urn:zeus:owner-delivery:1"
DELIVERY_FIELDS = {"schema", "job_id", "candidate_revision", "merge_revision", "deployed_revision",
                   "recorded_at", "evidence_refs", "report_url"}
REVISION = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE_REF = re.compile(r"^(sha256:)?[0-9a-f]{64}$")
REPORT_URL = re.compile(r"^https://github\.com/[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}"
                        r"(/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{0,300})?$")
MAX_EVIDENCE_REFS = 20


def _aware_timestamp(value) -> str:
    """An explicit timezone-aware ISO 8601 instant; a naive or malformed stamp is refused."""
    from datetime import datetime

    if type(value) is not str or not value:
        raise FleetRefused("delivery_invalid", "recorded_at")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FleetRefused("delivery_invalid", "recorded_at") from exc
    if parsed.utcoffset() is None:
        raise FleetRefused("delivery_invalid", "recorded_at")
    return value


def _delivery_revision(value, field: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or REVISION.fullmatch(value) is None:
        raise FleetRefused("delivery_invalid", field)
    return value


def validate_delivery(document) -> dict:
    """Strict validation of one owner-reported delivery document; returns the canonical copy.

    This is what the OWNER states after verifying the bindings from a preserved receipt. It is
    explicitly owner-reported evidence, never an independent GitHub or network verification, and
    it grants no authority: no job status, review verdict or release gate changes because of it.
    """
    if not isinstance(document, dict) or document.get("schema") != DELIVERY_SCHEMA:
        raise FleetRefused("delivery_schema")
    if set(document) != DELIVERY_FIELDS:
        raise FleetRefused("delivery_fields", "root")
    if not _token(document["job_id"]):
        raise FleetRefused("delivery_invalid", "job_id")
    refs = document["evidence_refs"]
    if not (isinstance(refs, list) and 1 <= len(refs) <= MAX_EVIDENCE_REFS):
        raise FleetRefused("delivery_invalid", "evidence_refs")
    for ref in refs:
        if type(ref) is not str or EVIDENCE_REF.fullmatch(ref) is None:
            raise FleetRefused("delivery_invalid", "evidence_refs")
    if len(set(refs)) != len(refs):
        raise FleetRefused("delivery_duplicate", "evidence_refs")
    url = document["report_url"]
    if url is not None and (type(url) is not str or REPORT_URL.fullmatch(url) is None):
        raise FleetRefused("delivery_invalid", "report_url")
    return {"schema": DELIVERY_SCHEMA, "job_id": document["job_id"],
            "candidate_revision": _delivery_revision(document["candidate_revision"], "candidate_revision"),
            "merge_revision": _delivery_revision(document["merge_revision"], "merge_revision"),
            "deployed_revision": _delivery_revision(document["deployed_revision"], "deployed_revision", True),
            "recorded_at": _aware_timestamp(document["recorded_at"]),
            "evidence_refs": list(refs), "report_url": url}


def delivery_view(record: dict) -> dict:
    """The safe projection of an owner delivery: the document fields and their authority label.

    `merged` and `deployed` stay distinguishable: a null deployed revision means the owner recorded
    a merge and nothing about a deployment. Absence of a record anywhere means unknown, never
    "not delivered", and delivery is never inferred from another job's timestamp or goal.
    """
    document = record["document"]
    return {"schema": DELIVERY_SCHEMA, "authority": "owner_recorded",
            "job_id": document["job_id"], "candidate_revision": document["candidate_revision"],
            "merge_revision": document["merge_revision"], "deployed_revision": document["deployed_revision"],
            "recorded_at": document["recorded_at"], "evidence_refs": list(document["evidence_refs"]),
            "report_url": document["report_url"]}


def repository_identity(path: str) -> str:
    """The lane repository as an identity: the digest of its normalized resolved path."""
    return digest(normalize_path(path))


def new_job(manifest: dict, manifest_sha256: str, lane: dict, goal: dict, dependencies: list[str],
            now: str) -> dict:
    """The durable job row. The manifest is frozen here; the job id is the operation id, so one
    operation can never map to two jobs or two lanes."""
    return {"id": manifest["id"], "operation_id": manifest["id"], "lane": lane["id"], "team": lane["team"],
            "repository": repository_identity(lane["repository"]), "status": QUEUED, "reason_code": None,
            "manifest": manifest, "manifest_sha256": manifest_sha256,
            "goal": {"path": goal["path"], "sha256": goal["sha256"], "criterion": goal["criterion"],
                     "base_revision": goal["base_revision"]},
            "dependencies": list(dependencies), "owner_token": None, "exit_code": None,
            "calls": {"reserved": None, "settled": None}, "receipt": None, "error_type": None,
            "created_at": now, "updated_at": now, "dispatched_at": None, "finished_at": None}


def binding(job: dict) -> dict:
    """What an identical enqueue must repeat exactly; anything else is a refused change."""
    return {"lane": job["lane"], "manifest_sha256": job["manifest_sha256"], "repository": job["repository"],
            "dependencies": list(job["dependencies"]), "goal": dict(job["goal"])}


def blocking_reason(job: dict, jobs: dict, config: dict) -> str | None:
    """Why this queued job cannot be admitted now, or None. Capacity and pause are fleet-wide and
    checked by the caller; this covers a stale budget, the lane, the dependencies and the path
    exclusion. A job frozen with ceilings other than the effective ones is never dispatched."""
    if job["manifest"].get("budget") != config["budget"]:
        return "budget_stale"
    reserving = [other for other in jobs.values() if other["status"] in RESERVING]
    if any(other["lane"] == job["lane"] for other in reserving):
        return "lane_busy"
    for dependency in job["dependencies"]:
        other = jobs.get(dependency)
        if other is None:
            return "dependency_missing"
        if other["status"] in DEPENDENCY_BLOCKING:
            return "dependency_" + other["status"]
        if other["status"] != ACCEPTED:
            return "dependency_waiting"
    for other in reserving:
        if other["repository"] == job["repository"] and conflicting_paths(
                job["manifest"]["plan"]["allowed_paths"], other["manifest"]["plan"]["allowed_paths"]):
            return "path_conflict"
    return None


def select_admission(config: dict, paused: bool, jobs: dict, budget_exhausted: bool) -> dict:
    """The one queued job to dispatch next (oldest first) and the reason every other queued job
    waits. At most `max_parallel` jobs reserve at once, one per lane. `config` carries the
    effective ceilings; the caller persists every observed reason in the same transaction."""
    queued = sorted((j for j in jobs.values() if j["status"] == QUEUED), key=lambda j: (j["created_at"], j["id"]))
    reserving = sum(1 for j in jobs.values() if j["status"] in RESERVING)
    blocked, chosen = {}, None
    for job in queued:
        if paused:
            reason = "paused"
        elif budget_exhausted:
            reason = "budget_exhausted"
        elif reserving >= config["max_parallel"]:
            reason = "capacity"
        else:
            reason = blocking_reason(job, jobs, config)
        if reason is None and chosen is None:
            chosen = job
            reserving += 1  # the next candidates see this claim: capacity, lane and paths
            jobs = {**jobs, job["id"]: {**job, "status": DISPATCHING}}
            continue
        blocked[job["id"]] = reason or "capacity"
    return {"job": chosen, "blocked": blocked, "paused": paused, "budget_exhausted": budget_exhausted}


def safe_code(reason) -> str:
    """Only the finite head of a reason leaves; colon details may carry raw text."""
    if not isinstance(reason, str):
        return "unknown"
    head, _, tail = reason.partition(":")
    code = "exception:" + tail.split(":", 1)[0] if head == "exception" else head
    return code if SAFE_CODE.fullmatch(code) else "unknown"


def classify_outcome(exit_code, receipt, job: dict, read_error: str | None = None) -> dict:
    """Bind the child's exit code to the exact durable lane operation row. Acceptance needs exit 0
    AND an accepted row with this job's operation id and manifest digest; anything nonzero,
    contradictory or missing is not promoted, and uncertainty stays `unknown`."""
    calls = {"reserved": None, "settled": None}
    if isinstance(receipt, dict) and isinstance(receipt.get("calls"), dict):
        calls = {k: receipt["calls"].get(k) if type(receipt["calls"].get(k)) is int else None
                 for k in ("reserved", "settled")}
    out = {"exit_code": exit_code if type(exit_code) is int else None, "calls": calls,
           "operation_status": receipt.get("status") if isinstance(receipt, dict) else None}
    if read_error is not None:
        return {**out, "status": UNKNOWN, "reason_code": "lane_read_uncertain", "error_type": read_error}
    if type(exit_code) is not int:
        return {**out, "status": UNKNOWN, "reason_code": "exit_unknown"}
    if receipt is None:
        # The child claims its row before any provider entry: no row and a refusal exit is definite.
        if exit_code != 0:
            return {**out, "status": FAILED, "reason_code": "child_refused"}
        return {**out, "status": UNKNOWN, "reason_code": "receipt_missing"}
    if (not isinstance(receipt, dict) or receipt.get("id") != job["operation_id"]
            or receipt.get("manifest_sha256") != job["manifest_sha256"]):
        return {**out, "status": UNKNOWN, "reason_code": "receipt_mismatch"}
    status, reason = receipt.get("status"), safe_code(receipt.get("reason_code"))
    if status == ACCEPTED:
        if exit_code == 0:
            return {**out, "status": ACCEPTED, "reason_code": reason}
        return {**out, "status": UNKNOWN, "reason_code": "exit_contradicts_receipt"}
    if status in {REJECTED, FAILED, EXHAUSTED}:
        if exit_code == 0:
            return {**out, "status": UNKNOWN, "reason_code": "exit_contradicts_receipt"}
        return {**out, "status": status, "reason_code": reason}
    if status == UNKNOWN:
        return {**out, "status": UNKNOWN, "reason_code": reason}
    return {**out, "status": UNKNOWN, "reason_code": "lane_operation_not_terminal"}


def job_view(job: dict) -> dict:
    """The wire projection of one job: identities, state, codes and counts only."""
    return {"id": job["id"], "lane": job["lane"], "team": job["team"], "status": job["status"],
            "reason_code": job.get("reason_code"), "operation_id": job["operation_id"],
            "goal": {"path": job["goal"]["path"], "criterion": job["goal"]["criterion"]},
            "dependencies": list(job["dependencies"]),
            "calls": {"reserved": job["calls"].get("reserved"), "settled": job["calls"].get("settled")},
            "created_at": job["created_at"], "updated_at": job["updated_at"]}


def projection(registry: dict | None, paused: bool, jobs: list[dict], deliveries: dict | None = None) -> dict:
    """`urn:zeus:fleet-status:1`: no manifest text, objectives, paths, schemas, DSNs or raw
    errors. The job list is the last JOB_SAMPLE by update; `active_job` is derived from every
    reserving job, including those outside the sample. `registry["config"]` is the effective
    configuration, so `budget` shows the ceilings new work must carry.

    `deliveries` (optional, job id -> owner delivery record) adds the safe `delivery` projection to
    the jobs that HAVE one. A job without a record keeps its exact previous shape: missing delivery
    evidence stays unknown and is never inferred from `accepted` or from another job."""
    if registry is None:
        return {"schema": STATUS_SCHEMA, "registered": False, "lanes": [], "jobs": []}
    config = registry["config"]
    active = {}
    for job in jobs:
        if job["status"] in RESERVING:
            active[job["lane"]] = job["id"]
    ordered = sorted(jobs, key=lambda j: (j["updated_at"], j["id"]), reverse=True)
    return {"schema": STATUS_SCHEMA, "registered": True, "id": config["id"], "paused": bool(paused),
            "max_parallel": config["max_parallel"], "budget": dict(config["budget"]),
            "accounting_mode": accounting_mode(config["budget"]),
            "lanes": [{"id": lane["id"], "team": lane["team"], "active_job": active.get(lane["id"])}
                      for lane in config["lanes"]],
            "jobs": [_with_delivery(job_view(job), (deliveries or {}).get(job["id"]))
                     for job in ordered[:JOB_SAMPLE]], "truncated": len(ordered) > JOB_SAMPLE}


def _with_delivery(view: dict, record) -> dict:
    return view if not isinstance(record, dict) else {**view, "delivery": delivery_view(record)}
