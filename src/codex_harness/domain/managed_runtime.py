"""Immutable managed runtimes and the work heartbeat of a managed Fleet target (HOST-RUNTIME.md).

A managed Fleet target (`domain.host_delivery.KIND_MANAGED`) never runs the live checkout. Each
reviewed revision is materialized ONCE, by the owner's own materializer, into a sealed directory
`<managed root>/runtimes/<revision>` whose manifest (`urn:zeus:managed-runtime:1`, written as the
small `runtime.json` attestation the incumbent `runtime_revision` already reads) names the revision,
its Git tree, the file count and content digest of its listing (`runtime-files.json`: every
materialized file by its Git blob id) and the digest of the dependency lockfile. A
sealed directory is never edited, overwritten or deleted, so the predecessor of every switch is
still there, byte for byte, when a rollback needs it.

What a running instance is doing is its own report, the heartbeat (`urn:zeus:managed-heartbeat:1`):
the instance and descriptor it belongs to, whether it has closed admission, how many children it
owns and how many Fleet reservations nobody owns. `work_verdict` is the only reader. A missing,
unreadable, stale, future-dated or mismatched heartbeat is `unknown`, and unknown is never idle.

Everything here is pure policy over dictionaries and text: no file, process, git or store access.
`DeliveryRefused` is reused so a refusal carries a fixed code and at most a field name.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from codex_harness.domain.host_delivery import (
    INSTANCE,
    KIND_MANAGED,
    REVISION,
    SHA256,
    DeliveryRefused,
    managed_runtime_root,
    receipt_identity,
    same_path,
    within_path,
)
from codex_harness.domain.model import digest

MANIFEST_SCHEMA = "urn:zeus:managed-runtime:1"
HEARTBEAT_SCHEMA = "urn:zeus:managed-heartbeat:1"
# The same attestation file name `adapters.host_delivery.runtime_revision` reads from a root that
# is not a checkout: the sealed manifest IS the owner's attestation of that runtime's revision.
MANIFEST_FILE = "runtime.json"
# The complete `[path, blob]` listing, kept out of the attestation so that stays small.
LISTING_FILE = "runtime-files.json"
SEAL_FILES = (MANIFEST_FILE, LISTING_FILE)
HEARTBEAT_FILE = "heartbeat.json"
LOCK_PATH = "uv.lock"
PACKAGE_MARKER = "src/codex_harness/__init__.py"
# What a runtime needs from a revision: the importable package tree and the dependency contract.
# Documentation, tests and tooling are not part of an operating runtime.
MATERIALIZED_PATHS = ("src", "pyproject.toml", LOCK_PATH)
# A stage that did not become a sealed runtime keeps this name as recovery evidence.
STAGE_PREFIX = ".stage-"
MANIFEST_FIELDS = {"schema", "revision", "tree", "files", "content_sha256", "environment_lock"}
HEARTBEAT_FIELDS = {"schema", "instance_id", "descriptor_sha256", "pid", "at", "admission",
                    "active", "unresolved"}
MAX_FILES = 5000

ADMISSION_OPEN, ADMISSION_PAUSED, ADMISSION_STOPPING = "open", "paused", "stopping"
ADMISSIONS = (ADMISSION_OPEN, ADMISSION_PAUSED, ADMISSION_STOPPING)
WORK_IDLE, WORK_BUSY, WORK_UNKNOWN = "idle", "busy", "unknown"
# A heartbeat older than this says nothing about now.
HEARTBEAT_MAX_AGE = 30.0
# Tolerated clock skew for a heartbeat that claims to come from the future.
HEARTBEAT_SKEW = 5.0

# The workloads a trusted launcher may start. `fleet` is the real existing Fleet CLI runner;
# `fixture` is the labelled controlled Fleet workload the tests use (a real FleetRunner over an
# in-memory Fleet whose children are real waiting processes). The choice is controller
# configuration, never a plan or descriptor field.
WORKLOAD_FLEET, WORKLOAD_FIXTURE = "fleet", "fixture"
WORKLOADS = (WORKLOAD_FLEET, WORKLOAD_FIXTURE)

GIT_OBJECT = re.compile(r"^[0-9a-f]{40}$")
# One segment of a materialized file path. Unlike the operation manifest grammar this admits the
# leading underscore of a Python package (`__init__.py`); traversal, `.git` and a trailing dot do not.
RUNTIME_SEGMENT = re.compile(r"^\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,253}$")


def safe_runtime_path(value) -> bool:
    """A forward-slash relative path inside a runtime: no root, drive, traversal or `.git`."""
    if type(value) is not str or not value or len(value) > 1024 or "\\" in value \
            or value.startswith("/"):
        return False
    return all(RUNTIME_SEGMENT.fullmatch(segment) is not None and segment.lower() != ".git"
               and not segment.endswith(".") for segment in value.split("/"))


class EnvironmentUnqualified(Exception):
    """The revision's dependency lockfile is not the one the fixed interpreter was qualified for.

    Deliberately not a `ContractError`: the candidate is not wrong, the host environment is not
    built for it yet. It is a named unavailable gate the owner clears by building and qualifying
    that environment (and registering its lockfile digest); nothing here installs anything.
    """

    def __init__(self, field: str = LOCK_PATH):
        super().__init__("managed runtime environment unqualified (" + field + ")")
        self.reason_code, self.field = "environment_unqualified", field


def blob_id(data: bytes) -> str:
    """The Git blob id of exactly these bytes, so a sealed file is compared with the tracked one."""
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def content_digest(files) -> str:
    return digest([list(entry) for entry in files])


def validate_listing(listing, manifest: dict | None = None) -> list:
    """The `[path, blob]` listing of a runtime: safe, sorted, unique, holding the package, and -
    when the manifest is given - exactly the count and content digest that manifest names."""
    if not (isinstance(listing, list) and 1 <= len(listing) <= MAX_FILES):
        raise DeliveryRefused("manifest_invalid", "files")
    checked = []
    for entry in listing:
        if not (isinstance(entry, list) and len(entry) == 2 and safe_runtime_path(entry[0])
                and entry[0] not in SEAL_FILES
                and type(entry[1]) is str and GIT_OBJECT.fullmatch(entry[1])):
            raise DeliveryRefused("manifest_invalid", "files[]")
        checked.append([entry[0], entry[1]])
    if [entry[0] for entry in checked] != sorted({entry[0] for entry in checked}):
        raise DeliveryRefused("manifest_invalid", "files[].order")
    if not any(entry[0] == PACKAGE_MARKER for entry in checked):
        raise DeliveryRefused("runtime_package_missing", "files")
    if manifest is not None and (len(checked) != manifest["files"]
                                 or content_digest(checked) != manifest["content_sha256"]):
        raise DeliveryRefused("manifest_listing_mismatch", "files")
    return checked


def new_manifest(revision: str, tree: str, files, environment_lock) -> tuple[dict, list]:
    """The deterministic manifest and listing of one materialized revision: identical inputs give
    identical bytes, which is what lets a lost response revalidate instead of re-sealing."""
    listing = validate_listing(sorted([path, blob] for path, blob in files))
    manifest = validate_manifest({"schema": MANIFEST_SCHEMA, "revision": revision, "tree": tree,
                                  "files": len(listing), "content_sha256": content_digest(listing),
                                  "environment_lock": environment_lock})
    return manifest, listing


def validate_manifest(document) -> dict:
    """Strict validation of a sealed runtime manifest, read back from disk as untrusted data."""
    if not isinstance(document, dict) or document.get("schema") != MANIFEST_SCHEMA:
        raise DeliveryRefused("manifest_schema")
    if set(document) != MANIFEST_FIELDS:
        raise DeliveryRefused("manifest_fields")
    if not (type(document["revision"]) is str and REVISION.fullmatch(document["revision"])):
        raise DeliveryRefused("manifest_invalid", "revision")
    if not (type(document["tree"]) is str and GIT_OBJECT.fullmatch(document["tree"])):
        raise DeliveryRefused("manifest_invalid", "tree")
    if not (type(document["files"]) is int and 1 <= document["files"] <= MAX_FILES):
        raise DeliveryRefused("manifest_invalid", "files")
    if not (type(document["content_sha256"]) is str and SHA256.fullmatch(document["content_sha256"])):
        raise DeliveryRefused("manifest_invalid", "content_sha256")
    lock = document["environment_lock"]
    if lock is not None and not (type(lock) is str and SHA256.fullmatch(lock)):
        raise DeliveryRefused("manifest_invalid", "environment_lock")
    return {key: document[key] for key in ("schema", "revision", "tree", "files",
                                           "content_sha256", "environment_lock")}


def manifest_digest(manifest: dict) -> str:
    return digest(manifest)


def check_runtime_path(target: dict, descriptor: dict) -> str:
    """The descriptor's root must be EXACTLY the sealed directory of its own revision.

    A descriptor that names another directory - the live checkout, a sibling revision, a path
    outside the managed root or a staging directory - is refused before anything is read from it.
    """
    if target.get("kind") != KIND_MANAGED:
        raise DeliveryRefused("target_not_managed", "kind")
    if descriptor.get("target_id") != target["target_id"]:
        raise DeliveryRefused("runtime_target_mismatch", "target_id")
    revision = descriptor.get("revision")
    if not (type(revision) is str and REVISION.fullmatch(revision)):
        raise DeliveryRefused("runtime_revision_invalid", "revision")
    expected = managed_runtime_root(target, revision)
    if not (same_path(descriptor.get("root"), expected)
            and within_path(descriptor.get("root"), target["root"])):
        raise DeliveryRefused("runtime_path_foreign", "root")
    return expected


def check_environment(lock_sha256, target: dict) -> None:
    """The fixed interpreter's environment was qualified for exactly this lockfile, or it was not."""
    if lock_sha256 != target["environment_lock"]:
        raise EnvironmentUnqualified()


def check_sealed(manifest: dict, listing: list, descriptor: dict, target: dict, observed) -> dict:
    """A sealed directory, as it is on disk NOW, is exactly the manifest of the descriptor's revision.

    `observed` is the adapter's fresh `[path, blob]` listing of every file under the directory other
    than the two seal files, or None when the directory holds something that is not a plain file.
    """
    if manifest["revision"] != descriptor["revision"]:
        raise DeliveryRefused("runtime_revision_mismatch", "revision")
    if observed is None or sorted(observed) != listing:
        raise DeliveryRefused("runtime_content_mismatch", "files")
    check_environment(manifest["environment_lock"], target)
    return manifest


def new_heartbeat(receipt: dict, *, at: str, admission: str, active: int, unresolved: int) -> dict:
    return {"schema": HEARTBEAT_SCHEMA, "instance_id": receipt["instance_id"],
            "descriptor_sha256": receipt["descriptor_sha256"], "pid": receipt["pid"], "at": at,
            "admission": admission, "active": int(active), "unresolved": int(unresolved)}


def _count(value) -> bool:
    return type(value) is int and 0 <= value <= 10 ** 6


def _unknown(reason_code: str) -> dict:
    return {"state": WORK_UNKNOWN, "reason_code": reason_code, "active": None, "unresolved": None,
            "paused": None}


def work_verdict(heartbeat, receipt, *, now: datetime, max_age: float = HEARTBEAT_MAX_AGE,
                 require_paused: bool = False) -> dict:
    """What the running instance is doing, from its own heartbeat, bound to its own receipt.

    `idle` needs all of: a well formed heartbeat, of the instance and descriptor and pid the valid
    startup receipt names, no older than `max_age` and not from the future, with no owned child and
    no unresolved Fleet reservation - and, when `require_paused`, with admission observed closed.
    Everything else is `busy` (a definite count of work, or a pause not yet acknowledged) or
    `unknown`; nothing here ever turns an absence of evidence into an idle instance.
    """
    identity = receipt_identity(receipt, present=receipt is not None)
    if identity["state"] != "valid":
        return _unknown("heartbeat_receipt_" + identity["state"])
    if heartbeat is None:
        return _unknown("heartbeat_missing")
    if not isinstance(heartbeat, dict) or heartbeat.get("schema") != HEARTBEAT_SCHEMA \
            or set(heartbeat) != HEARTBEAT_FIELDS:
        return _unknown("heartbeat_unreadable")
    if not (type(heartbeat["instance_id"]) is str and INSTANCE.fullmatch(heartbeat["instance_id"])
            and heartbeat["admission"] in ADMISSIONS and _count(heartbeat["active"])
            and _count(heartbeat["unresolved"])):
        return _unknown("heartbeat_unreadable")
    if (heartbeat["instance_id"] != identity["instance_id"]
            or heartbeat["descriptor_sha256"] != identity["descriptor_sha256"]
            or heartbeat["pid"] != receipt.get("pid")):
        return _unknown("heartbeat_mismatched")
    try:
        at = datetime.fromisoformat(heartbeat["at"])
        age = (now - at).total_seconds()
    except (TypeError, ValueError):
        return _unknown("heartbeat_unreadable")
    if age < -HEARTBEAT_SKEW:
        return _unknown("heartbeat_future")
    if age > max_age:
        return _unknown("heartbeat_stale")
    paused = heartbeat["admission"] != ADMISSION_OPEN
    observed = {"active": heartbeat["active"], "unresolved": heartbeat["unresolved"],
                "paused": paused}
    if heartbeat["active"] or heartbeat["unresolved"]:
        return {"state": WORK_BUSY, "reason_code": "work_active" if heartbeat["active"]
                else "work_unresolved", **observed}
    if require_paused and not paused:
        return {"state": WORK_BUSY, "reason_code": "pause_unacknowledged", **observed}
    return {"state": WORK_IDLE, "reason_code": None, **observed}


__all__ = ["ADMISSIONS", "ADMISSION_OPEN", "ADMISSION_PAUSED", "ADMISSION_STOPPING",
           "HEARTBEAT_FILE", "HEARTBEAT_MAX_AGE", "HEARTBEAT_SCHEMA", "LISTING_FILE", "LOCK_PATH",
           "MANIFEST_FILE", "MANIFEST_SCHEMA", "MATERIALIZED_PATHS", "MAX_FILES", "PACKAGE_MARKER",
           "SEAL_FILES", "STAGE_PREFIX", "validate_listing",
           "WORKLOADS", "WORKLOAD_FIXTURE", "WORKLOAD_FLEET", "WORK_BUSY", "WORK_IDLE",
           "WORK_UNKNOWN", "EnvironmentUnqualified", "blob_id", "check_environment",
           "check_runtime_path", "check_sealed", "content_digest", "manifest_digest",
           "new_heartbeat", "new_manifest", "safe_runtime_path", "validate_manifest",
           "work_verdict"]
