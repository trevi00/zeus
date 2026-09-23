"""Owner-approved host delivery plans and their durable stage policy (INV-HOST-DELIVERY-001).

A delivery plan is one owner-authored document (`urn:zeus:host-delivery:1`) that lives in Git and
is read at an explicit commit. It names an EXISTING release candidate (release id, revision, tree,
the incumbent policy hash it was evaluated under and the canonical repository), the named CI checks
that must finish successfully for that exact head, the host target it activates and the descriptor
that target must end up consuming. It is strict versioned JSON: no shell command, no argv, no
source text, no path and no credential is ever accepted from a plan, and nothing in a plan is
executed or interpreted as an instruction.

What a target IS - its root, its state files, its service identity and its kind - is host
configuration (`urn:zeus:host-delivery-targets:1`), registered separately by the owner. A plan may
only NAME a registered target id, so a candidate can never select another scheduled task, another
path or another policy for itself. The canary is the same: a plan names one incumbent fixed check
id from `CANARY_CHECKS`, never executable text.

Everything here is pure policy over dictionaries: no store, process, git, subprocess or provider
access, and no value ever reaches an error message - only the field name does. (`os.path.normcase`
and `os.path.normpath` are used for host paths: both are pure text functions that touch no
filesystem.) Approval is not granted here either: this module can only RECOGNIZE the approval that
`application.releases` already recorded, and a plan that claims a review, a check or an activation
proves nothing.
"""
from __future__ import annotations

import os.path
import re

from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import safe_relative_path

PLAN_SCHEMA = "urn:zeus:host-delivery:1"
REGISTRY_SCHEMA = "urn:zeus:host-delivery-targets:1"
DESCRIPTOR_SCHEMA = "urn:zeus:host-descriptor:1"
RECEIPT_SCHEMA = "urn:zeus:host-startup-receipt:1"
STATUS_SCHEMA = "urn:zeus:host-delivery-status:1"
TICK_SCHEMA = "urn:zeus:host-delivery-tick:1"

PLAN_FIELDS = {"schema", "plan_id", "release_id", "revision", "tree", "policy_hash", "repository",
               "required_checks", "target_id", "expected_descriptor", "target_descriptor",
               "canary_check_id", "ci_timeout_seconds", "consumption_timeout_seconds"}
TARGET_DESCRIPTOR_FIELDS = {"revision", "worker_image", "profile_digest"}
REGISTRY_FIELDS = {"schema", "targets"}
TARGET_FIELDS = {"target_id", "kind", "root", "state_dir", "service"}
# The managed Fleet target adds exactly the owner facts an immutable runtime needs: the source
# repository its revisions are resolved from (also the host configuration root of its child), the
# fixed interpreter and the digest of the dependency lockfile that interpreter was qualified for.
MANAGED_TARGET_FIELDS = TARGET_FIELDS | {"source", "python", "environment_lock"}
DESCRIPTOR_FIELDS = ("schema", "target_id", "root", "revision", "worker_image", "profile_digest",
                     "predecessor")
RECEIPT_FIELDS = {"schema", "target_id", "instance_id", "pid", "started_at", "runtime_root",
                  "module_root", "descriptor_sha256", "revision", "worker_image", "profile_digest"}
PIN_FIELDS = {"revision", "path", "sha256"}

# Host target kinds this harness knows how to own. The Windows scheduled task is the current host's
# real service; `process` is the owned-child-process target used on POSIX and in tests. Both carry
# the identical descriptor, switch and startup-receipt contract.
KIND_SCHEDULED_TASK = "windows_scheduled_task"
KIND_PROCESS = "process"
# The opt-in managed Fleet target (HOST-RUNTIME.md): `root` is a managed root of sealed per-revision
# runtime directories, and the descriptor names the one directory of its revision. The two kinds
# above keep their registry fields and their meaning unchanged.
KIND_MANAGED = "managed_fleet"
TARGET_KINDS = (KIND_SCHEDULED_TASK, KIND_PROCESS, KIND_MANAGED)
# Where the sealed runtime of one revision lives under a managed root.
RUNTIMES_DIR = "runtimes"

# What the instance ACTUALLY on a target is, relative to the authority to replace it. Descriptor
# identity and authority over a running instance are two different facts: a receipt that does not
# match the descriptor being started says only that this is not the intended instance - never that
# whatever is running there may be stopped and retired.
INSTANCE_INTENDED = "intended"
INSTANCE_AUTHORIZED = "authorized_predecessor"
INSTANCE_INTERRUPTED = "owned_stopped"
INSTANCE_ABSENT = "absent"
INSTANCE_FOREIGN = "foreign"
INSTANCE_UNKNOWN = "unknown"
# The three states a start may act on. Everything else refuses BEFORE the stop and the cleanup.
REPLACEABLE_INSTANCES = frozenset({INSTANCE_AUTHORIZED, INSTANCE_INTERRUPTED, INSTANCE_ABSENT})
# A managed start refused by its activation gate (Fleet debt held or unreadable after the committed
# pause, the pause changed between commit and read, the pause itself not committed or acknowledged,
# or no authority): nothing was launched, and any pause already committed stays. A restoration waits.
ACTIVATION_GATE_CODES = frozenset({"fleet_debt_held", "fleet_debt_unknown", "fleet_control_changed",
                                   "fleet_pause_unknown", "fleet_authority_unconfigured"})

# The incumbent fixed canary check ids. A plan selects one of these by id; the check itself lives in
# the adapter and exercises the ACTUAL service contract of the target it was written for.
CANARY_COLLECT = "collect_monitor_source"
CANARY_FLEET = "fleet_worker_operation"
CANARY_STARTUP = "startup_identity"
CANARY_CHECKS = (CANARY_COLLECT, CANARY_FLEET, CANARY_STARTUP)

# "the image or the profile does not change in this delivery", stated explicitly rather than left
# out: an absent binding would be indistinguishable from an unknown one.
UNCHANGED = "unchanged"

MAX_REQUIRED_CHECKS = 16
MAX_TARGETS = 16
# Two distinct definite failures of one stage stop the delivery and hand it to the owner.
MAX_STAGE_ATTEMPTS = 2
MIN_CI_TIMEOUT, MAX_CI_TIMEOUT = 60, 6 * 3600
MIN_CONSUMPTION_TIMEOUT, MAX_CONSUMPTION_TIMEOUT = 10, 900

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# A Git tree object id exactly as `git rev-parse <revision>^{tree}` prints it: 40 hex in a SHA-1
# repository, 64 in a SHA-256 one. It is an object id, not a content digest, so it is validated
# apart from the SHA256 fields above and compared only by exact equality, never padded or rehashed.
TREE_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
# A GitHub check or status context name as it is reported, and nothing that could be a command.
CHECK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()#:-]{0,119}$")
# `github:owner/repo` or `local:/path` as `adapters.git.GitWorkspace.target_identity` writes it.
REPOSITORY = re.compile(r"^(github:[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}|local:[^\s]{1,400})$")
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,200}$")
INSTANCE = re.compile(r"^[0-9a-f]{32}$")

# The durable stage path of one delivery. Every stage before `active` is an open state a restart
# must resume; a stage is entered by writing the durable intent BEFORE the external action it
# names, so a lost response can only ever reconcile what already happened.
REGISTERED = "registered"
AWAITING_REVIEW = "awaiting_review"
PUBLISHING = "publishing"
AWAITING_CI = "awaiting_ci"
MERGE_INTENDED = "merge_intended"
MERGED = "merged"
DRAIN_INTENDED = "drain_intended"
SWITCHING = "switching"
AWAITING_CONSUMPTION = "awaiting_consumption"
ACTIVE = "active"
# Explicit non-progress states. Each preserves the stage it left, the error type, the evidence and
# the next action; none of them is ever rewritten into a success.
BLOCKED = "blocked"
ROLLING_BACK = "rolling_back"
ROLLED_BACK = "rolled_back"
FAILED = "failed"

STAGE_ORDER = (REGISTERED, AWAITING_REVIEW, PUBLISHING, AWAITING_CI, MERGE_INTENDED, MERGED,
               DRAIN_INTENDED, SWITCHING, AWAITING_CONSUMPTION, ACTIVE)
TERMINAL_STAGES = frozenset({ACTIVE, ROLLED_BACK, FAILED})
HALTED_STAGES = frozenset({BLOCKED, ROLLING_BACK, ROLLED_BACK, FAILED})
# The stages a tick may no longer advance at all. `rolling_back` is deliberately NOT one of them:
# a restoration is owed work, and a controller that stopped selecting it would leave the host on a
# descriptor that failed its own canary.
STOPPED_STAGES = frozenset({BLOCKED, ROLLED_BACK, FAILED})
OPEN_STAGES = frozenset(STAGE_ORDER) - {ACTIVE}
# The stages that have already changed something outside this store: a restart reconciles the
# external identity before it is allowed to act again.
EXTERNAL_STAGES = frozenset({PUBLISHING, AWAITING_CI, MERGE_INTENDED, MERGED, DRAIN_INTENDED,
                             SWITCHING, AWAITING_CONSUMPTION, ROLLING_BACK})

# One tick's outcome. `pending` is an external wait that released its lease, not a failure and not
# a success; `unavailable` is an outage with its exception TYPE; `blocked` and `refused` are
# definite and exit nonzero.
OUTCOME_PROGRESSED = "progressed"
OUTCOME_PENDING = "pending"
OUTCOME_ACTIVE = "active"
OUTCOME_IDLE = "idle"
OUTCOME_BUSY = "controller_busy"
OUTCOME_DISABLED = "disabled"
OUTCOME_BLOCKED = "blocked"
OUTCOME_REFUSED = "refused"
OUTCOME_CONFLICT = "conflict"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_ROLLED_BACK = "rolled_back"
OUTCOME_UNREGISTERED = "plan_unregistered"
FAILED_OUTCOMES = frozenset({OUTCOME_BLOCKED, OUTCOME_REFUSED, OUTCOME_CONFLICT,
                             OUTCOME_UNAVAILABLE, OUTCOME_UNREGISTERED})

# CI states. Only every required check FINISHED SUCCESSFULLY for the intended head is a pass;
# missing, queued, in progress, skipped, cancelled, neutral and failed are all not-a-pass, each
# under its own code.
CI_PASSED, CI_PENDING, CI_FAILED, CI_HEAD_CHANGED = "passed", "pending", "failed", "head_changed"

# The structured transitions of this component (domain.observation REGISTRY): scheduling is
# general, the evidence/check stages are development, and the switch, the rollback and every
# operational block are operations.
EVENT_STAGE = "general.delivery_stage_entered"
EVENT_CHECK = "development.delivery_check_observed"
EVENT_SWITCHED = "operations.delivery_switched"
EVENT_ROLLBACK = "operations.delivery_rollback"
EVENT_BLOCKED = "operations.delivery_blocked"

AUTHORITY = ("host_delivery; approval remains the existing Releases lead+conductor record and the "
             "ReleaseQueue fence. A delivery receipt proves publication, observed CI, merge, an "
             "atomically switched descriptor and a consumed startup identity - never a review "
             "verdict, a semantic acceptance or a qualified live host")


class DeliveryRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("host delivery refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


class LifecycleInterrupted(Exception):
    """Ownership ended DURING a lifecycle operation that had already changed the host.

    It is deliberately not a `ContractError`: a refusal means nothing happened, while this names an
    effect that is already out in the world - the service of this target was stopped, and only then
    did the fence turn out to be gone. The operation stops there: nothing is cleaned up, nothing is
    started, and the coordinator reports an ambiguous effect so the next owner reconciles this
    target. The stopped instance's own evidence is preserved rather than erased or called cancelled.
    """

    def __init__(self, effect: str, cause: Exception):
        super().__init__(effect)
        self.effect, self.cause = effect, cause


def _token(value) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


def _hex(value, pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _fields(document, expected, name: str) -> None:
    if not isinstance(document, dict):
        raise DeliveryRefused("plan_invalid", name)
    if set(document) != expected:
        raise DeliveryRefused("plan_fields", name)


def _bounded_int(value, low: int, high: int) -> bool:
    # `bool` is refused here exactly as everywhere else: its type is bool, not int.
    return type(value) is int and low <= value <= high


def normal_path(value) -> str:
    """One comparable spelling of a host path. Pure text: nothing is resolved or opened here."""
    text = str(value or "").strip().replace("\\", "/").rstrip("/")
    return os.path.normcase(os.path.normpath(text)) if text else ""


def same_path(left, right) -> bool:
    return bool(normal_path(left)) and normal_path(left) == normal_path(right)


def within_path(child, root) -> bool:
    """Whether `child` IS `root` or lies under it; a sibling with a shared prefix does not."""
    parent, inner = normal_path(root), normal_path(child)
    if not parent or not inner:
        return False
    return inner == parent or inner.startswith(parent.rstrip(os.sep) + os.sep)


def safe_error_type(value) -> str | None:
    """An exception TYPE name and nothing else; any other text is `unknown` rather than relayed."""
    if value is None:
        return None
    return value if _token(value) else "unknown"


def validate_pin(pin) -> dict:
    """The Git pin the plan itself was read from: a commit, a safe relative path, exact bytes."""
    _fields(pin, PIN_FIELDS, "pin")
    if not _hex(pin["revision"], REVISION):
        raise DeliveryRefused("pin_invalid", "pin.revision")
    if not safe_relative_path(pin["path"]):
        raise DeliveryRefused("pin_invalid", "pin.path")
    if not _hex(pin["sha256"], SHA256):
        raise DeliveryRefused("pin_invalid", "pin.sha256")
    return {key: pin[key] for key in sorted(PIN_FIELDS)}


def _target_descriptor(document) -> dict:
    """The candidate side of a descriptor: a clean host revision and the two immutable bindings,
    each either an exact identity or the explicit word `unchanged`."""
    _fields(document, TARGET_DESCRIPTOR_FIELDS, "target_descriptor")
    if not _hex(document["revision"], REVISION):
        raise DeliveryRefused("descriptor_invalid", "target_descriptor.revision")
    image = document["worker_image"]
    if image != UNCHANGED and not (type(image) is str and IMAGE.fullmatch(image) is not None):
        raise DeliveryRefused("descriptor_invalid", "target_descriptor.worker_image")
    profile = document["profile_digest"]
    if profile != UNCHANGED and not _hex(profile, SHA256):
        raise DeliveryRefused("descriptor_invalid", "target_descriptor.profile_digest")
    return {key: document[key] for key in sorted(TARGET_DESCRIPTOR_FIELDS)}


def validate_plan(document) -> dict:
    """Strict validation of one owner-approved delivery plan; returns the canonical copy.

    Unknown or missing fields, a malformed identity, an empty or oversized check list, a duplicate
    check name, a canary id this harness does not implement and an out-of-range timeout are refused
    before anything is stored. Nothing here contacts a release, a repository or a host: this says
    only that the DOCUMENT is well formed.
    """
    if not isinstance(document, dict) or document.get("schema") != PLAN_SCHEMA:
        raise DeliveryRefused("plan_schema")
    _fields(document, PLAN_FIELDS, "root")
    for key in ("plan_id", "release_id", "target_id"):
        if not _token(document[key]):
            raise DeliveryRefused("plan_invalid", key)
    if not _hex(document["revision"], REVISION):
        raise DeliveryRefused("plan_invalid", "revision")
    if not _hex(document["tree"], TREE_ID):
        raise DeliveryRefused("plan_invalid", "tree")
    if not _hex(document["policy_hash"], SHA256):
        raise DeliveryRefused("plan_invalid", "policy_hash")
    repository = document["repository"]
    if not (type(repository) is str and REPOSITORY.fullmatch(repository) is not None):
        raise DeliveryRefused("plan_invalid", "repository")
    checks = document["required_checks"]
    if not (isinstance(checks, list) and 1 <= len(checks) <= MAX_REQUIRED_CHECKS
            and all(type(c) is str and CHECK_NAME.fullmatch(c) is not None for c in checks)):
        raise DeliveryRefused("plan_invalid", "required_checks")
    if len(set(checks)) != len(checks):
        raise DeliveryRefused("plan_duplicate", "required_checks")
    expected = document["expected_descriptor"]
    # `null` is the first activation of a target that has no descriptor yet; it is not a wildcard.
    if expected is not None and not _hex(expected, SHA256):
        raise DeliveryRefused("plan_invalid", "expected_descriptor")
    if document["canary_check_id"] not in CANARY_CHECKS:
        raise DeliveryRefused("plan_invalid", "canary_check_id")
    if not _bounded_int(document["ci_timeout_seconds"], MIN_CI_TIMEOUT, MAX_CI_TIMEOUT):
        raise DeliveryRefused("plan_invalid", "ci_timeout_seconds")
    if not _bounded_int(document["consumption_timeout_seconds"], MIN_CONSUMPTION_TIMEOUT,
                        MAX_CONSUMPTION_TIMEOUT):
        raise DeliveryRefused("plan_invalid", "consumption_timeout_seconds")
    return {"schema": PLAN_SCHEMA, "plan_id": document["plan_id"], "release_id": document["release_id"],
            "revision": document["revision"], "tree": document["tree"],
            "policy_hash": document["policy_hash"], "repository": repository,
            "required_checks": list(checks), "target_id": document["target_id"],
            "expected_descriptor": expected,
            "target_descriptor": _target_descriptor(document["target_descriptor"]),
            "canary_check_id": document["canary_check_id"],
            "ci_timeout_seconds": document["ci_timeout_seconds"],
            "consumption_timeout_seconds": document["consumption_timeout_seconds"]}


def plan_digest(plan: dict) -> str:
    return digest(plan)


def _target(entry, index: int) -> dict:
    name = "targets[" + str(index) + "]"
    managed = isinstance(entry, dict) and entry.get("kind") == KIND_MANAGED
    fields = MANAGED_TARGET_FIELDS if managed else TARGET_FIELDS
    _fields(entry, fields, name)
    if not _token(entry["target_id"]):
        raise DeliveryRefused("target_invalid", name + ".target_id")
    if entry["kind"] not in TARGET_KINDS:
        raise DeliveryRefused("target_invalid", name + ".kind")
    paths = ("root", "state_dir", "source", "python") if managed else ("root", "state_dir")
    for key in paths:
        # A host path IS owner configuration here, but it is still never taken from a candidate and
        # never interpolated into a command line.
        if not (type(entry[key]) is str and entry[key].strip() and len(entry[key]) <= 400):
            raise DeliveryRefused("target_invalid", name + "." + key)
    if not (type(entry["service"]) is str and TOKEN.fullmatch(entry["service"]) is not None):
        raise DeliveryRefused("target_invalid", name + ".service")
    if managed:
        _managed_target(entry, name)
    return {key: entry[key] for key in sorted(fields)}


def _managed_target(entry: dict, name: str) -> None:
    """The extra owner facts of a managed target: absolute, and three disjoint trees.

    The managed root, the state directory and the source checkout may not contain one another, so
    sealing a runtime can never write into the live checkout, a state file can never land inside a
    sealed runtime, and a runtime can never be sealed from inside itself.
    """
    for key in ("root", "state_dir", "source", "python"):
        if not os.path.isabs(entry[key]):
            raise DeliveryRefused("target_invalid", name + "." + key)
    for left, right in (("root", "state_dir"), ("root", "source"), ("state_dir", "source")):
        if within_path(entry[left], entry[right]) or within_path(entry[right], entry[left]):
            raise DeliveryRefused("target_overlap", name + "." + left)
    if not _hex(entry["environment_lock"], SHA256):
        raise DeliveryRefused("target_invalid", name + ".environment_lock")


def managed_runtime_root(target: dict, revision: str) -> str:
    """The sealed runtime directory of one revision under a managed root. Pure text: the path is
    derived from the owner registry and the reviewed revision, never taken from a plan."""
    return os.path.join(target["root"], RUNTIMES_DIR, revision)


def validate_targets(document) -> dict:
    """The authorized host target registry: what a target id MEANS on this host.

    This is host configuration, registered by the owner and deliberately separate from candidate
    content. A plan may name one of these ids and nothing else; it can never introduce a root, a
    state directory, a service or a kind of its own.
    """
    if not isinstance(document, dict) or document.get("schema") != REGISTRY_SCHEMA:
        raise DeliveryRefused("registry_schema")
    _fields(document, REGISTRY_FIELDS, "root")
    targets = document["targets"]
    if not (isinstance(targets, list) and 1 <= len(targets) <= MAX_TARGETS):
        raise DeliveryRefused("registry_invalid", "targets")
    entries = [_target(entry, index) for index, entry in enumerate(targets)]
    identifiers = [entry["target_id"] for entry in entries]
    if len(set(identifiers)) != len(identifiers):
        raise DeliveryRefused("registry_duplicate", "targets[].target_id")
    return {"schema": REGISTRY_SCHEMA, "targets": entries}


def resolve_descriptor(target: dict, plan: dict, current: dict | None) -> dict:
    """The COMPLETE descriptor this delivery must make the target consume.

    The root comes from the registered target, never from the plan; for a managed target it is the
    sealed directory of the descriptor's revision under the registered managed root, so the
    predecessor and the candidate always name two different immutable runtimes. `unchanged` is resolved against
    the descriptor the target is actually running now, and a target with no current descriptor
    cannot resolve it at all - that is a refusal, never a guess or an empty binding. `predecessor`
    is the digest of exactly the descriptor this switch replaces, so a rollback restores a full
    tuple rather than a remembered revision.
    """
    plan_descriptor = plan["target_descriptor"]
    resolved = {}
    for key in ("worker_image", "profile_digest"):
        value = plan_descriptor[key]
        if value != UNCHANGED:
            resolved[key] = value
            continue
        if not isinstance(current, dict) or current.get(key) in (None, UNCHANGED):
            raise DeliveryRefused("unchanged_without_predecessor", "target_descriptor." + key)
        resolved[key] = current[key]
    root = (managed_runtime_root(target, plan_descriptor["revision"])
            if target.get("kind") == KIND_MANAGED else target["root"])
    return {"schema": DESCRIPTOR_SCHEMA, "target_id": target["target_id"], "root": root,
            "revision": plan_descriptor["revision"], "worker_image": resolved["worker_image"],
            "profile_digest": resolved["profile_digest"],
            "predecessor": None if current is None else descriptor_digest(current)}


def descriptor_digest(descriptor: dict) -> str:
    """One identity per descriptor, over exactly the bound fields and in a fixed order."""
    return digest({key: descriptor.get(key) for key in DESCRIPTOR_FIELDS})


def validate_descriptor(document) -> dict:
    """A descriptor read back from the host: the file a service was pointed at, checked as data."""
    if not isinstance(document, dict) or document.get("schema") != DESCRIPTOR_SCHEMA:
        raise DeliveryRefused("descriptor_schema")
    if set(document) != set(DESCRIPTOR_FIELDS):
        raise DeliveryRefused("descriptor_fields")
    if not _token(document["target_id"]):
        raise DeliveryRefused("descriptor_invalid", "target_id")
    if not _hex(document["revision"], REVISION):
        raise DeliveryRefused("descriptor_invalid", "revision")
    if not (type(document["root"]) is str and document["root"].strip()):
        raise DeliveryRefused("descriptor_invalid", "root")
    if not (type(document["worker_image"]) is str and IMAGE.fullmatch(document["worker_image"])):
        raise DeliveryRefused("descriptor_invalid", "worker_image")
    if not _hex(document["profile_digest"], SHA256):
        raise DeliveryRefused("descriptor_invalid", "profile_digest")
    if document["predecessor"] is not None and not _hex(document["predecessor"], SHA256):
        raise DeliveryRefused("descriptor_invalid", "predecessor")
    return {key: document[key] for key in DESCRIPTOR_FIELDS}


def validate_receipt(document) -> dict:
    """The startup evidence a launched process reports about ITSELF, checked as untrusted data."""
    if not isinstance(document, dict) or document.get("schema") != RECEIPT_SCHEMA:
        raise DeliveryRefused("receipt_schema")
    if set(document) != RECEIPT_FIELDS:
        raise DeliveryRefused("receipt_fields")
    if not _token(document["target_id"]):
        raise DeliveryRefused("receipt_invalid", "target_id")
    if not _hex(document["instance_id"], INSTANCE):
        raise DeliveryRefused("receipt_invalid", "instance_id")
    if not _bounded_int(document["pid"], 1, 2 ** 31 - 1):
        raise DeliveryRefused("receipt_invalid", "pid")
    for key in ("started_at", "runtime_root", "module_root"):
        if not (type(document[key]) is str and document[key].strip() and len(document[key]) <= 400):
            raise DeliveryRefused("receipt_invalid", key)
    if not _hex(document["descriptor_sha256"], SHA256):
        raise DeliveryRefused("receipt_invalid", "descriptor_sha256")
    if not _hex(document["revision"], REVISION):
        raise DeliveryRefused("receipt_invalid", "revision")
    if not (type(document["worker_image"]) is str and IMAGE.fullmatch(document["worker_image"])):
        raise DeliveryRefused("receipt_invalid", "worker_image")
    if not _hex(document["profile_digest"], SHA256):
        raise DeliveryRefused("receipt_invalid", "profile_digest")
    return {key: document[key] for key in sorted(RECEIPT_FIELDS)}


def _check_row(row) -> dict | None:
    """One observed CI row reduced to (name, state); anything unreadable is dropped, not guessed."""
    if not isinstance(row, dict):
        return None
    name, state = row.get("name"), row.get("state")
    if type(name) is not str or type(state) is not str:
        return None
    return {"name": name, "state": state}


def ci_verdict(required, observed, head: str, observed_head=None) -> dict:
    """Whether the named checks all finished successfully for EXACTLY the intended head.

    `observed` is a list of `{name, state}` rows the adapter normalized from the provider, where
    `state` is `success`, `pending` or `failure`. A required check that is absent, still running,
    skipped, cancelled, neutral or failed is not a pass - each under its own code - and a head that
    moved is `head_changed`, which goes to requalification rather than being rebased into the old
    acceptance. Extra checks the plan does not require are ignored: the plan is the authority over
    what must pass, never the provider's current workflow list.
    """
    if observed_head is not None and observed_head != head:
        return {"state": CI_HEAD_CHANGED, "reason_code": "ci_head_changed", "missing": [],
                "failed": [], "pending": [], "head": observed_head}
    rows = {row["name"]: row["state"] for row in (_check_row(r) for r in observed or []) if row}
    missing = sorted(name for name in required if name not in rows)
    failed = sorted(name for name in required if rows.get(name) == "failure")
    pending = sorted(name for name in required if rows.get(name) == "pending")
    if failed:
        return {"state": CI_FAILED, "reason_code": "ci_check_failed", "missing": missing,
                "failed": failed, "pending": pending, "head": head}
    if missing or pending:
        return {"state": CI_PENDING,
                "reason_code": "ci_check_missing" if missing else "ci_check_pending",
                "missing": missing, "failed": failed, "pending": pending, "head": head}
    return {"state": CI_PASSED, "reason_code": None, "missing": [], "failed": [], "pending": [],
            "head": head}


def consumption_verdict(descriptor: dict, receipt, *, expected_instance=None) -> dict:
    """Whether the process that started is REALLY running the descriptor that was switched to.

    Every bound field is compared, and the runtime identity is compared FIRST: the root the process
    says it actually imported from must be exactly the owner-registered root of this target, and the
    package it says it loaded must lie inside that root. Only then do the revision, the effective
    worker image and the effective profile digest the runtime OBSERVED about itself have to equal
    the ones this delivery requested - which is what makes an old runtime started with a new
    descriptor a refusal rather than an activation, however alive its pid is.

    A receipt that is absent, malformed, from another target, from another root, from the previous
    instance or bound to any other identity never grants activation; it is a definite mismatch with
    its own code, not a retryable unknown.
    """
    if receipt is None:
        return {"consumed": False, "reason_code": "receipt_missing", "instance_id": None}
    try:
        checked = validate_receipt(receipt)
    except DeliveryRefused as exc:
        return {"consumed": False, "reason_code": exc.reason_code, "instance_id": None}
    observed = {"instance_id": checked["instance_id"], "pid": checked["pid"],
                "runtime_root": checked["runtime_root"], "module_root": checked["module_root"],
                "revision": checked["revision"]}
    if not same_path(checked["runtime_root"], descriptor["root"]):
        # The process is running from somewhere other than the root this target is registered at.
        return {"consumed": False, "reason_code": "receipt_runtime_root_mismatch", **observed}
    if not within_path(checked["module_root"], checked["runtime_root"]):
        # It imported its code from outside the root it claims to be running: not this runtime.
        return {"consumed": False, "reason_code": "receipt_module_root_foreign", **observed}
    expected_digest = descriptor_digest(descriptor)
    for key, expected in (("target_id", descriptor["target_id"]), ("revision", descriptor["revision"]),
                          ("worker_image", descriptor["worker_image"]),
                          ("profile_digest", descriptor["profile_digest"]),
                          ("descriptor_sha256", expected_digest)):
        if checked[key] != expected:
            return {"consumed": False, "reason_code": "receipt_" + key + "_mismatch", **observed}
    if expected_instance is not None and checked["instance_id"] == expected_instance:
        # The file still describes the process that was there BEFORE this switch: a stale receipt is
        # not evidence of the new one, however well its fields match.
        return {"consumed": False, "reason_code": "receipt_stale_instance", **observed}
    return {"consumed": True, "reason_code": None, **observed}


def validate_replacement(authorization) -> dict | None:
    """The durable authority to replace ONE observed instance of a target, checked as data.

    It is produced by the coordinator from its own durable intent - the identity captured before
    the descriptor was replaced, or the candidate this intent itself launched - and never by the
    host adapter from whatever receipt happens to be lying on the target. `None` is the honest
    "nothing here may be replaced": a clean target may still be started, and a running instance may
    not be touched at all.
    """
    if authorization is None:
        return None
    if not isinstance(authorization, dict):
        raise DeliveryRefused("replacement_invalid", "replaces")
    descriptor_sha256 = authorization.get("descriptor_sha256")
    instance_id = authorization.get("instance_id")
    launch = authorization.get("launch")
    if descriptor_sha256 is not None and not _hex(descriptor_sha256, SHA256):
        raise DeliveryRefused("replacement_invalid", "replaces.descriptor_sha256")
    if instance_id is not None and not _hex(instance_id, INSTANCE):
        raise DeliveryRefused("replacement_invalid", "replaces.instance_id")
    if launch is not None and not isinstance(launch, dict):
        raise DeliveryRefused("replacement_invalid", "replaces.launch")
    return {"descriptor_sha256": descriptor_sha256, "instance_id": instance_id,
            "launch": dict(launch) if isinstance(launch, dict) else None}


def receipt_identity(receipt, *, present: bool = False) -> dict:
    """WHO the receipt on a target says is running there, as untrusted data.

    Three different facts, deliberately not collapsed: `absent` (no receipt file at all), `valid`
    (a well formed receipt that names an instance) and `unreadable` (a file that exists but is
    missing, malformed, oversized or contradictory). An unreadable receipt identifies nobody, and is
    never read as an absence.
    """
    if receipt is None:
        return {"state": "unreadable" if present else "absent", "instance_id": None,
                "descriptor_sha256": None, "target_id": None}
    try:
        checked = validate_receipt(receipt)
    except DeliveryRefused:
        return {"state": "unreadable", "instance_id": None, "descriptor_sha256": None,
                "target_id": None}
    return {"state": "valid", "instance_id": checked["instance_id"],
            "descriptor_sha256": checked["descriptor_sha256"], "target_id": checked["target_id"]}


def same_launch(observed, authorized) -> bool:
    """Whether the launch record on the target is EXACTLY the one this delivery recorded writing.

    The record is written only by this component, under the target's lifecycle guard, and names the
    descriptor, the start time and the process or service identity of that launch. Exact equality -
    not a live pid alone - is what binds a running instance to a transition this delivery made.
    """
    return bool(observed) and isinstance(observed, dict) and observed == authorized


def _instance(state: str, reason_code, instance_id=None, evidence=None) -> dict:
    return {"state": state, "reason_code": reason_code, "instance_id": instance_id,
            "evidence": evidence}


def instance_authority(descriptor: dict, observed, authorization=None) -> dict:
    """Classify the instance actually on this target, and say whether it may be replaced.

    `observed` is what the adapter READ from the target before touching anything: the receipt
    document and whether that file exists at all, the launch record this component wrote and
    whether that file exists at all, and whether an instance is running (`None` when that could not
    be observed). `authorization` is the durable authority above.

    * `intended` - the incumbent `consumption_verdict` shows the live instance is really running
      exactly this descriptor: recognized, never stopped, retired or started again.
    * `authorized_predecessor` - the running instance is the exact instance the durable transition
      named, by its own receipt or by this delivery's own launch record.
    * `owned_stopped` - an instance this delivery owns is no longer running and its transition was
      interrupted: its recorded effect is reconciled and the start is resumed once.
    * `absent` - POSITIVE evidence of an empty target: no receipt, no launch record, nothing alive.
    * `foreign` / `unknown` - anything else, including a missing, malformed, contradictory or
      simply unauthorized instance. These refuse before any stop or cleanup, because an instance
      that is not the intended one is not thereby a replaceable one.
    """
    authority = validate_replacement(authorization)
    observation = observed or {}
    running = observation.get("running")
    if running is None:
        # The target could not be observed at all; an unknown is never a licence to replace.
        return _instance(INSTANCE_UNKNOWN, "instance_liveness_unknown", evidence="liveness")
    receipt = observation.get("receipt")
    verdict = consumption_verdict(descriptor, receipt)
    if verdict["consumed"]:
        if running:
            return _instance(INSTANCE_INTENDED, None, verdict["instance_id"], "receipt")
        # This delivery's own instance, proven by its own receipt, is gone: resume the transition.
        return _instance(INSTANCE_INTERRUPTED, "instance_intended_stopped", verdict["instance_id"],
                         "receipt")
    identity = receipt_identity(receipt, present=bool(observation.get("receipt_present")))
    launch = observation.get("launch")
    owned_launch = (authority is not None and authority["launch"] is not None
                    and same_launch(launch, authority["launch"]))
    if identity["state"] == "valid":
        authorized = (authority is not None
                      and identity["descriptor_sha256"] == authority["descriptor_sha256"]
                      and (identity["instance_id"] == authority["instance_id"]
                           or (authority["instance_id"] is None and owned_launch)))
        if not authorized:
            contradictory = (authority is not None
                             and identity["instance_id"] == authority["instance_id"])
            return _instance(INSTANCE_FOREIGN,
                             "instance_contradictory" if contradictory else "instance_not_authorized",
                             identity["instance_id"], "receipt")
        if running:
            return _instance(INSTANCE_AUTHORIZED, None, identity["instance_id"], "receipt")
        return _instance(INSTANCE_INTERRUPTED, "instance_authorized_stopped",
                         identity["instance_id"], "receipt")
    if identity["state"] == "unreadable":
        # A receipt file that says nothing identifies nobody, alive or not.
        return _instance(INSTANCE_UNKNOWN, "instance_receipt_unreadable", evidence="receipt")
    if owned_launch:
        # No startup identity was ever confirmed, so the trusted launch record of THIS delivery is
        # what reconciles the instance it started.
        return _instance(INSTANCE_AUTHORIZED if running else INSTANCE_INTERRUPTED,
                         None if running else "instance_authorized_stopped", None, "launch")
    if running:
        return _instance(INSTANCE_UNKNOWN, "instance_unidentified", evidence="liveness")
    if observation.get("launch_present") or isinstance(launch, dict):
        owned = (isinstance(launch, dict)
                 and launch.get("descriptor_sha256") in _owned_digests(descriptor, authority))
        if owned:
            return _instance(INSTANCE_INTERRUPTED, "instance_launch_stopped", None, "launch")
        return _instance(INSTANCE_UNKNOWN, "instance_absence_unknown", evidence="launch")
    return _instance(INSTANCE_ABSENT, None, None, "absence")


def _owned_digests(descriptor: dict, authority) -> set:
    """The descriptors an interrupted launch record of THIS delivery may legitimately name."""
    digests = {descriptor_digest(descriptor)}
    if authority is not None and authority["descriptor_sha256"] is not None:
        digests.add(authority["descriptor_sha256"])
    return digests


def release_gate(record, plan: dict, parent: str | None) -> dict:
    """What the EXISTING release record says about this exact plan; nothing here approves anything.

    The reviews are re-derived from the record - the author's own lead and a conductor, both
    accepting exactly this revision with evidence - and the candidate's revision, tree, evaluator
    policy hash and canonical repository must be exactly the ones the plan names. A plan can
    therefore never introduce an approval, relax an evaluator or point a reviewed acceptance at
    another tree. `awaiting_review` is a real projected state: registration may legitimately precede
    the review, and it never runs.
    """
    if not isinstance(record, dict):
        return {"state": OUTCOME_REFUSED, "reason_code": "release_missing", "status": None}
    candidate = record.get("candidate") or {}
    status = record.get("status")
    for key, expected in (("revision", plan["revision"]), ("tree", plan["tree"])):
        if candidate.get(key) != expected:
            return {"state": OUTCOME_REFUSED, "reason_code": "release_" + key + "_mismatch",
                    "status": status}
    if record.get("policy_hash") != plan["policy_hash"]:
        return {"state": OUTCOME_REFUSED, "reason_code": "release_policy_mismatch", "status": status}
    if candidate.get("repository") != plan["repository"]:
        # A legacy candidate without a recorded repository is `legacy_unverified` for the merge
        # owner; for an activation of this host it is simply not a verified target.
        return {"state": OUTCOME_REFUSED, "reason_code": "release_repository_mismatch", "status": status}
    accepted = {review.get("actor") for review in record.get("reviews") or []
                if review.get("accepted") is True and review.get("revision") == plan["revision"]
                and review.get("evidence")}
    if status in {"rejected", "cancelled", "rolled_back"} or str(status).startswith("superseded"):
        return {"state": OUTCOME_REFUSED, "reason_code": "release_" + str(status), "status": status}
    if parent is None or parent not in accepted or "conductor" not in accepted:
        return {"state": AWAITING_REVIEW, "reason_code": "release_reviews_incomplete", "status": status}
    if status not in {"reviewed", "verified", "active"}:
        return {"state": AWAITING_REVIEW, "reason_code": "release_not_reviewed", "status": status}
    return {"state": "approved", "reason_code": None, "status": status}


def new_intent(plan: dict, plan_sha256: str, now: str) -> dict:
    """The durable intent of one delivery, written before any external effect of any stage."""
    return {"id": plan["plan_id"], "plan_id": plan["plan_id"], "release_id": plan["release_id"],
            "target_id": plan["target_id"], "plan_sha256": plan_sha256, "stage": REGISTERED,
            "previous_stage": None, "outcome": None, "reason_code": None, "error_type": None,
            "attempts": 0, "revision": plan["revision"], "head": None, "pr_number": None,
            "pr_url": None, "merged_revision": None, "descriptor_sha256": None,
            "previous_descriptor_sha256": None, "descriptor": None, "previous_descriptor": None,
            # The identity of the instance this delivery may replace, captured BEFORE the
            # descriptor is replaced, and the identity of the candidate it launches itself. A
            # rollback replaces the candidate, never the predecessor it is restoring.
            "previous_instance_id": None, "previous_launch": None,
            "candidate_instance_id": None, "candidate_launch": None,
            "instance_id": None, "expected_active": None,
            "expected_active_set": False, "canary": None, "rollback": None, "stage_deadline": None,
            "stage_entered_at": now, "created_at": now, "updated_at": now, "evidence": []}


def next_stage(stage: str) -> str:
    """The stage that follows a completed one; `active` is terminal and follows nothing."""
    if stage not in STAGE_ORDER:
        raise DeliveryRefused("stage_unknown", "stage")
    index = STAGE_ORDER.index(stage)
    return STAGE_ORDER[min(index + 1, len(STAGE_ORDER) - 1)]


def stage_next_action(stage: str, outcome=None) -> str:
    """The bounded next action for one delivery; never a command and never an authorization."""
    if stage == ACTIVE:
        return "observe_active_runtime"
    if stage == ROLLING_BACK:
        return "restore_predecessor"
    if stage in {BLOCKED, FAILED}:
        return "owner_review"
    if stage == ROLLED_BACK:
        return "owner_requalify_candidate"
    if stage == AWAITING_REVIEW:
        return "await_independent_review"
    if stage == AWAITING_CI:
        return "await_required_checks"
    if stage == AWAITING_CONSUMPTION:
        return "await_startup_receipt"
    if outcome == OUTCOME_UNAVAILABLE:
        return "await_dependency"
    return "tick"


def delivery_progress(row: dict, intent, descriptor_row) -> dict:
    """What one registered plan looks like now: identities, digests, stage, fixed codes and counts.

    No path, no descriptor body, no check output, no PR title, no exception message and no
    credential is projected: a reader gets ids, digests, states and reason codes only. An absent
    intent is `registered`, never invented progress, and an absent descriptor is unknown rather
    than an empty tuple. `startup_observed` is the launched instance's OWN accepted receipt and is
    deliberately separate from `consumed`: a runtime is observed BEFORE the canary that decides
    whether it may become the active one, and only `consumed` is that activation.
    """
    plan = row["plan"]
    stage = (intent or {}).get("stage") or REGISTERED
    active = (descriptor_row or {}).get("descriptor") or None
    view = {"plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "revision": plan["revision"], "plan_sha256": row["plan_sha256"], "pin": dict(row["pin"]),
            "required_checks": len(plan["required_checks"]), "canary_check_id": plan["canary_check_id"],
            "stage": stage, "outcome": (intent or {}).get("outcome"),
            "reason_code": (intent or {}).get("reason_code"),
            "error_type": (intent or {}).get("error_type"),
            "attempts": int((intent or {}).get("attempts") or 0),
            "head": (intent or {}).get("head"), "pr_number": (intent or {}).get("pr_number"),
            "merged_revision": (intent or {}).get("merged_revision"),
            "intended_descriptor_sha256": (intent or {}).get("descriptor_sha256"),
            "instance_id": (intent or {}).get("instance_id"),
            "canary": (intent or {}).get("canary"), "rollback": (intent or {}).get("rollback"),
            "active_descriptor_sha256": None if active is None else descriptor_digest(active),
            "active_revision": None if active is None else active.get("revision"),
            "startup_observed": bool((descriptor_row or {}).get("startup_observed")),
            "consumed": bool((descriptor_row or {}).get("consumed")),
            "runtime": _runtime_view((intent or {}).get("runtime")),
            "work": _work_view((intent or {}).get("work")),
            "updated_at": (intent or {}).get("updated_at") or row.get("updated_at")}
    view["next_action"] = stage_next_action(stage, view["outcome"])
    return view


def _runtime_view(record) -> dict | None:
    """The sealed runtime a managed delivery bound, as a digest and a revision; never its path."""
    if not isinstance(record, dict):
        return None
    return {"revision": record.get("revision"), "manifest_sha256": record.get("manifest_sha256"),
            "files": record.get("files"), "recovered": bool(record.get("recovered"))}


def _work_view(record) -> dict | None:
    """The last drain observation of a managed target: a state, a code and two counts."""
    if not isinstance(record, dict):
        return None
    return {key: record.get(key) for key in ("state", "reason_code", "active", "unresolved",
                                             "paused")}


def delivery_status(rows, intents: dict, descriptors: dict, *, enabled: bool) -> dict:
    """`urn:zeus:host-delivery-status:1`: the read-only projection of every registered plan.

    A collected status is a projection of durable records only. It is never evidence of an active
    host, a qualified release or a successful canary - `stage` says what was PROVEN, and every
    absent observation stays unknown.
    """
    plans = [delivery_progress(row, intents.get(row["plan_id"]), descriptors.get(row["plan"]["target_id"]))
             for row in sorted(rows, key=lambda r: r["plan_id"])]
    counts = {stage: sum(1 for view in plans if view["stage"] == stage)
              for stage in (*STAGE_ORDER, BLOCKED, ROLLING_BACK, ROLLED_BACK, FAILED)}
    return {"schema": STATUS_SCHEMA, "registered": bool(plans), "enabled": bool(enabled),
            "deliveries": plans, "counts": {k: v for k, v in counts.items() if v},
            "targets": [target_progress(descriptors[target_id]) for target_id in sorted(descriptors)],
            "authority": AUTHORITY}


def target_progress(row: dict) -> dict:
    """What ONE host target is recorded as running: digests, ids and states, never a descriptor
    body, a root, a service name or a path. `consumed` false is a switch that was not an
    activation, and an absent row is simply not listed - never an empty tuple that reads as clean."""
    return {"target_id": row["target_id"], "descriptor_sha256": row.get("descriptor_sha256"),
            "startup_observed": bool(row.get("startup_observed")),
            "observed_instance_id": row.get("observed_instance_id"),
            "observed_revision": row.get("observed_revision"),
            "revision": (row.get("descriptor") or {}).get("revision"),
            "worker_image": (row.get("descriptor") or {}).get("worker_image"),
            "profile_digest": (row.get("descriptor") or {}).get("profile_digest"),
            "predecessor": (row.get("descriptor") or {}).get("predecessor"),
            "consumed": bool(row.get("consumed")), "instance_id": row.get("instance_id"),
            "plan_id": row.get("plan_id"), "release_id": row.get("release_id"),
            "rolled_back": bool(row.get("rolled_back")), "updated_at": row.get("updated_at"),
            "history": len(row.get("history") or [])}


__all__ = ["ACTIVATION_GATE_CODES", "ACTIVE", "AUTHORITY", "AWAITING_CI", "AWAITING_CONSUMPTION", "AWAITING_REVIEW",
           "BLOCKED", "CANARY_CHECKS", "CANARY_COLLECT", "CANARY_FLEET", "CANARY_STARTUP",
           "CI_FAILED", "CI_HEAD_CHANGED", "CI_PASSED", "CI_PENDING", "DESCRIPTOR_FIELDS",
           "DESCRIPTOR_SCHEMA", "EVENT_BLOCKED", "EVENT_CHECK", "EVENT_ROLLBACK", "EVENT_STAGE",
           "EVENT_SWITCHED", "EXTERNAL_STAGES", "FAILED", "FAILED_OUTCOMES", "HALTED_STAGES",
           "INSTANCE_ABSENT", "INSTANCE_AUTHORIZED", "INSTANCE_FOREIGN", "INSTANCE_INTENDED",
           "INSTANCE_INTERRUPTED", "INSTANCE_UNKNOWN", "REPLACEABLE_INSTANCES",
           "KIND_MANAGED", "KIND_PROCESS", "KIND_SCHEDULED_TASK", "MANAGED_TARGET_FIELDS",
           "MAX_STAGE_ATTEMPTS", "MERGED", "MERGE_INTENDED", "RUNTIMES_DIR",
           "OPEN_STAGES", "OUTCOME_ACTIVE", "OUTCOME_BLOCKED", "OUTCOME_BUSY", "OUTCOME_CONFLICT",
           "OUTCOME_DISABLED", "OUTCOME_IDLE", "OUTCOME_PENDING", "OUTCOME_PROGRESSED",
           "OUTCOME_REFUSED", "OUTCOME_ROLLED_BACK", "OUTCOME_UNAVAILABLE", "OUTCOME_UNREGISTERED",
           "PLAN_SCHEMA", "PUBLISHING", "RECEIPT_SCHEMA", "REGISTERED", "REGISTRY_SCHEMA",
           "ROLLED_BACK", "ROLLING_BACK", "STAGE_ORDER", "STATUS_SCHEMA", "STOPPED_STAGES",
           "SWITCHING",
           "TARGET_KINDS", "TERMINAL_STAGES", "TICK_SCHEMA", "UNCHANGED", "DeliveryRefused",
           "LifecycleInterrupted",
           "ci_verdict", "consumption_verdict", "delivery_progress", "delivery_status",
           "descriptor_digest", "instance_authority", "managed_runtime_root", "new_intent",
           "next_stage", "normal_path",
           "plan_digest", "receipt_identity",
           "release_gate", "resolve_descriptor", "safe_error_type", "same_launch", "same_path",
           "stage_next_action", "target_progress", "validate_descriptor",
           "validate_pin", "validate_plan", "validate_receipt", "validate_replacement",
           "validate_targets", "within_path"]
