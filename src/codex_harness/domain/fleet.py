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

CONFIG_SCHEMA = "urn:zeus:fleet:1"
STATUS_SCHEMA = "urn:zeus:fleet-status:1"
CONFIG_FIELDS = {"schema", "id", "max_parallel", "budget", "lanes"}
BUDGET_FIELDS = {"per_host", "total"}
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
    _fields(budget, BUDGET_FIELDS, name)
    if not (_integer(budget["per_host"]) and _integer(budget["total"]) and budget["per_host"] > 0
            and budget["total"] >= budget["per_host"]):
        raise FleetRefused("config_invalid", name)
    return {"per_host": budget["per_host"], "total": budget["total"]}


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
    """An explicit operator grant over the effective ceilings (compare-and-swap on the total):
    the stated expected total must be the current effective total, both ceilings must be valid
    and monotonically nondecreasing, and at least one must increase. Never a reset."""
    new = validate_budget(requested)
    if not _integer(expected_total) or expected_total != prior["total"]:
        raise FleetRefused("budget_expected_mismatch", "expected_total")
    if new["per_host"] < prior["per_host"] or new["total"] < prior["total"]:
        raise FleetRefused("budget_decrease", "budget")
    if new == prior:
        raise FleetRefused("budget_no_increase", "budget")
    return new


def sanitized_config(config: dict) -> dict:
    """What may be displayed: identities and ceilings; never paths, schemas or namespaces."""
    return {"schema": config["schema"], "id": config["id"], "max_parallel": config["max_parallel"],
            "budget": dict(config["budget"]),
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


def projection(registry: dict | None, paused: bool, jobs: list[dict]) -> dict:
    """`urn:zeus:fleet-status:1`: no manifest text, objectives, paths, schemas, DSNs or raw
    errors. The job list is the last JOB_SAMPLE by update; `active_job` is derived from every
    reserving job, including those outside the sample. `registry["config"]` is the effective
    configuration, so `budget` shows the ceilings new work must carry."""
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
            "lanes": [{"id": lane["id"], "team": lane["team"], "active_job": active.get(lane["id"])}
                      for lane in config["lanes"]],
            "jobs": [job_view(job) for job in ordered[:JOB_SAMPLE]], "truncated": len(ordered) > JOB_SAMPLE}
