"""Approved backlog plans and deterministic successor selection (INV-FLEET-BACKLOG-001).

An approved backlog is one owner-authored document (`urn:zeus:fleet-backlog:1`) that lives in Git
and is read at an explicit commit: a plan id, the repository identity its manifests belong to, an
enabled/paused flag and a finite list of items. An item names an EXISTING portfolio project and
criterion, one fleet lane, the operation manifest it admits as `path + revision + sha256`, a
priority and the item ids it depends on. Items express owner-approved goals; nothing here is an
executable command, and no text from a plan is ever interpreted as an instruction.

Everything in this module is pure policy over dictionaries: no store, process, git or provider
access, and no value ever reaches an error message - only the field name does. Selection is
deterministic and dependency-aware: an open durable intent is resumed before any new item is
picked, eligible items are ordered by priority then by stable id, and a blocked item never starves
another eligible one. A selection is an admission intent, never a completion, a review verdict, a
release or a deployment receipt.
"""
from __future__ import annotations

import re

from codex_harness.domain.fleet import ACCEPTED, DEPENDENCY_BLOCKING
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import safe_relative_path

PLAN_SCHEMA = "urn:zeus:fleet-backlog:1"
STATUS_SCHEMA = "urn:zeus:fleet-backlog-status:1"
TICK_SCHEMA = "urn:zeus:fleet-backlog-tick:1"

PLAN_FIELDS = {"schema", "plan_id", "repository", "enabled", "items"}
ITEM_FIELDS = {"id", "project_id", "criterion_id", "lane", "manifest_path", "manifest_revision",
               "manifest_sha256", "priority", "dependencies"}
PIN_FIELDS = {"revision", "path", "sha256"}
# The pinned identity of one item's manifest; an intent is bound to exactly these values and a
# later plan that changes any of them refuses that item instead of editing queued work.
ITEM_PIN_FIELDS = ("lane", "manifest_path", "manifest_revision", "manifest_sha256")

MAX_ITEMS = 64
MAX_DEPENDENCIES = 8
MAX_PRIORITY = 10_000
# Two distinct definite refusals of the same item stop that item and hand it to the owner; a
# transient unavailable input is not an attempt and is not counted here.
MAX_ATTEMPTS = 2

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Durable intent states. `selected` and `intended` are the two open states an interrupted process
# can leave behind: `selected` means the intent exists and the pinned input was not read yet,
# `intended` means the exact job identity is known and the enqueue is unconfirmed.
SELECTED, INTENDED, ENQUEUED, BLOCKED, CONFLICT = "selected", "intended", "enqueued", "blocked", "conflict"
INTENT_STATES = frozenset({SELECTED, INTENDED, ENQUEUED, BLOCKED, CONFLICT})
OPEN_STATES = frozenset({SELECTED, INTENDED})

# What one item looks like right now. `enqueued` carries the authoritative Fleet status beside it,
# so accepted, failed, unknown and still-pending work never collapse into one label.
ITEM_PENDING, ITEM_OPEN, ITEM_ENQUEUED = "pending", "open", "enqueued"
ITEM_BLOCKED, ITEM_CONFLICT, ITEM_UNKNOWN = "blocked", "conflict", "unknown"

# Tick and selection outcomes. Idle, an exhausted backlog, a paused plan, a paused fleet and an
# unavailable input are distinct recorded facts; none of them is a success.
OUTCOME_SELECTED = "selected"
OUTCOME_ENQUEUED = "enqueued"
OUTCOME_EXHAUSTED = "backlog_exhausted"
OUTCOME_BLOCKED = "blocked"
OUTCOME_PLAN_PAUSED = "plan_paused"
OUTCOME_FLEET_PAUSED = "fleet_paused"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_UNREGISTERED = "plan_unregistered"
OUTCOME_REFUSED = "refused"
OUTCOME_CONFLICT = "conflict"
# Outcomes a command reports with a nonzero exit: the tick could not do what it was asked to do.
FAILED_OUTCOMES = frozenset({OUTCOME_UNREGISTERED, OUTCOME_UNAVAILABLE, OUTCOME_REFUSED, OUTCOME_CONFLICT})

# What a selection receipt asserts, spelled out wherever it is projected: an accepted job is an
# accepted lane operation and nothing more.
AUTHORITY = ("backlog_selection; an accepted job means an accepted lane operation only, never a "
             "review verdict, a merge, a release or a deployment")


class BacklogRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("fleet backlog refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _token(value) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


def _hex(value, pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _fields(document, expected, name: str) -> None:
    if not isinstance(document, dict):
        raise BacklogRefused("plan_invalid", name)
    if set(document) != expected:
        raise BacklogRefused("plan_fields", name)


def validate_pin(pin) -> dict:
    """The Git pin the plan itself was read from: a full commit id, a safe repository-relative
    path and the digest of the exact bytes."""
    _fields(pin, PIN_FIELDS, "pin")
    if not _hex(pin["revision"], REVISION):
        raise BacklogRefused("pin_invalid", "pin.revision")
    if not safe_relative_path(pin["path"]):
        raise BacklogRefused("pin_invalid", "pin.path")
    if not _hex(pin["sha256"], SHA256):
        raise BacklogRefused("pin_invalid", "pin.sha256")
    return {k: pin[k] for k in sorted(PIN_FIELDS)}


def _item(item, index: int) -> dict:
    name = "items[" + str(index) + "]"
    _fields(item, ITEM_FIELDS, name)
    for key in ("id", "project_id", "criterion_id", "lane"):
        if not _token(item[key]):
            raise BacklogRefused("item_invalid", name + "." + key)
    path = item["manifest_path"]
    if not (safe_relative_path(path) and path.lower().endswith(".json")):
        raise BacklogRefused("item_invalid", name + ".manifest_path")
    if not _hex(item["manifest_revision"], REVISION):
        raise BacklogRefused("item_invalid", name + ".manifest_revision")
    if not _hex(item["manifest_sha256"], SHA256):
        raise BacklogRefused("item_invalid", name + ".manifest_sha256")
    # `bool` is refused here exactly as everywhere else: its type is bool, not int.
    if type(item["priority"]) is not int or not 0 <= item["priority"] <= MAX_PRIORITY:
        raise BacklogRefused("item_invalid", name + ".priority")
    dependencies = item["dependencies"]
    if not (isinstance(dependencies, list) and len(dependencies) <= MAX_DEPENDENCIES
            and all(_token(d) for d in dependencies) and len(set(dependencies)) == len(dependencies)):
        raise BacklogRefused("item_invalid", name + ".dependencies")
    return {**{k: item[k] for k in sorted(ITEM_FIELDS - {"dependencies"})},
            "dependencies": list(dependencies)}


def _refuse_cycles(items: list[dict]) -> None:
    """Depth-first colouring over the item graph; a back edge is a refused plan."""
    edges = {item["id"]: item["dependencies"] for item in items}
    state: dict[str, int] = {}

    def walk(node: str) -> None:
        state[node] = 1
        for dependency in edges[node]:
            if state.get(dependency) == 1:
                raise BacklogRefused("dependency_cycle", "items[].dependencies")
            if dependency not in state:
                walk(dependency)
        state[node] = 2

    for item in items:
        if item["id"] not in state:
            walk(item["id"])


def validate_plan(document) -> dict:
    """Strict validation of one owner-approved backlog document; returns the canonical copy.

    Unknown or missing fields, duplicate item ids, a dependency on an item this plan does not
    define, a self dependency, a cycle, an unsafe or non-JSON manifest path, a malformed pin and a
    priority outside its bounds are all refused before anything is stored.
    """
    if not isinstance(document, dict) or document.get("schema") != PLAN_SCHEMA:
        raise BacklogRefused("plan_schema")
    _fields(document, PLAN_FIELDS, "root")
    if not _token(document["plan_id"]):
        raise BacklogRefused("plan_invalid", "plan_id")
    if not _hex(document["repository"], SHA256):
        raise BacklogRefused("plan_invalid", "repository")
    if type(document["enabled"]) is not bool:
        raise BacklogRefused("plan_invalid", "enabled")
    items = document["items"]
    if not (isinstance(items, list) and 1 <= len(items) <= MAX_ITEMS):
        raise BacklogRefused("plan_invalid", "items")
    canonical = [_item(item, index) for index, item in enumerate(items)]
    identifiers = [item["id"] for item in canonical]
    if len(set(identifiers)) != len(identifiers):
        raise BacklogRefused("plan_duplicate", "items[].id")
    known = set(identifiers)
    for item in canonical:
        for dependency in item["dependencies"]:
            if dependency == item["id"]:
                raise BacklogRefused("dependency_self", "items[].dependencies")
            if dependency not in known:
                raise BacklogRefused("dependency_unknown", "items[].dependencies")
    _refuse_cycles(canonical)
    return {"schema": PLAN_SCHEMA, "plan_id": document["plan_id"], "repository": document["repository"],
            "enabled": document["enabled"], "items": canonical}


def plan_digest(plan: dict) -> str:
    return digest(plan)


def item_pin(item: dict) -> dict:
    """The pinned scope identity of one item: its lane and the exact manifest bytes it admits."""
    return {key: item[key] for key in ITEM_PIN_FIELDS}


def intent_pin(intent: dict) -> dict:
    return {key: intent.get(key) for key in ITEM_PIN_FIELDS}


def intent_key(plan_id: str, item_id: str) -> str:
    return plan_id + ":" + item_id


def new_intent(plan_id: str, item: dict, now: str) -> dict:
    """The durable intent row, written BEFORE the pinned input is read and before any enqueue.

    It carries the goal binding (project and criterion), the pin and the scope (lane and manifest
    digest) so a restarted or duplicated tick recognizes exactly one identity for this item.
    """
    return {"id": intent_key(plan_id, item["id"]), "plan_id": plan_id, "item_id": item["id"],
            "project_id": item["project_id"], "criterion_id": item["criterion_id"],
            **item_pin(item), "state": SELECTED, "job_id": None, "job_manifest_sha256": None,
            "goal_sha256": None, "base_revision": None, "attempts": 0, "reason_code": None,
            "created_at": now, "updated_at": now, "enqueued_at": None}


def job_matches(intent: dict, job: dict) -> bool:
    """An already created job is THIS intent's job only when its frozen manifest digest and bound
    goal bytes are the recorded ones. An equal id under any other binding is a conflict, never
    evidence that the enqueue succeeded."""
    goal = job.get("goal") if isinstance(job.get("goal"), dict) else {}
    return (job.get("id") == intent.get("job_id")
            and job.get("manifest_sha256") == intent.get("job_manifest_sha256")
            and goal.get("sha256") == intent.get("goal_sha256")
            and goal.get("base_revision") == intent.get("base_revision"))


def reconcile_intent(intent: dict, jobs: dict, now: str) -> dict | None:
    """Meet one open durable intent with the authoritative Fleet rows; None when nothing changes.

    This is the response-loss and restart path: the job may already exist because a previous tick
    enqueued it and never saw the answer. A matching row settles the intent as `enqueued`; a row
    with the same id and another binding settles it as `conflict` for the owner.
    """
    if intent.get("state") not in OPEN_STATES or not intent.get("job_id"):
        return None
    job = jobs.get(intent["job_id"])
    if job is None:
        return None
    if not job_matches(intent, job):
        return {**intent, "state": CONFLICT, "reason_code": "job_binding_conflict", "updated_at": now}
    return {**intent, "state": ENQUEUED, "reason_code": None,
            "enqueued_at": intent.get("enqueued_at") or now, "updated_at": now}


def item_progress(item: dict, intent, jobs: dict) -> dict:
    """What one plan item looks like now: its identities, its pin, its durable state, the Fleet
    status of its job when there is one, and a fixed reason code. Missing evidence is unknown."""
    view = {"item_id": item["id"], "project_id": item["project_id"], "criterion_id": item["criterion_id"],
            "lane": item["lane"], "priority": item["priority"],
            "pin": {"revision": item["manifest_revision"], "sha256": item["manifest_sha256"],
                    "path": item["manifest_path"]},
            "dependencies": list(item["dependencies"]), "job_id": None, "job_status": None,
            "reason_code": None, "attempts": 0}
    if intent is None:
        return {**view, "state": ITEM_PENDING}
    view = {**view, "job_id": intent.get("job_id"), "attempts": intent.get("attempts", 0),
            "reason_code": intent.get("reason_code")}
    if intent_pin(intent) != item_pin(item):
        # The plan moved under an item that already has a durable identity: refuse, never rebind.
        return {**view, "state": ITEM_CONFLICT, "reason_code": "pin_changed"}
    state = intent.get("state")
    if state == CONFLICT:
        return {**view, "state": ITEM_CONFLICT, "reason_code": intent.get("reason_code") or "conflict"}
    if state == BLOCKED:
        return {**view, "state": ITEM_BLOCKED}
    if state == ENQUEUED:
        job = jobs.get(intent.get("job_id"))
        if job is None:
            return {**view, "state": ITEM_UNKNOWN, "reason_code": "job_missing"}
        return {**view, "state": ITEM_ENQUEUED, "job_status": job.get("status"),
                "reason_code": job.get("reason_code")}
    return {**view, "state": ITEM_OPEN}


def dependency_reason(progress: dict) -> str | None:
    """None when a dependency is satisfied - its Fleet job is `accepted` - and a fixed code
    otherwise. A failed dependency blocks its dependents only; it starves nothing else."""
    state = progress["state"]
    if state == ITEM_ENQUEUED:
        if progress["job_status"] == ACCEPTED:
            return None
        if progress["job_status"] in DEPENDENCY_BLOCKING:
            return "dependency_" + progress["job_status"]
        return "dependency_waiting"
    if state in {ITEM_CONFLICT, ITEM_BLOCKED, ITEM_UNKNOWN}:
        return "dependency_" + state
    return "dependency_waiting"


def select(plan: dict, intents: dict, jobs: dict, fleet_paused: bool = False) -> dict:
    """The one item this tick may work on, plus the reason every other item waits.

    Order: open durable intents first (an interrupted enqueue is completed before new work is
    admitted), then dependency-satisfied pending items by priority and then by stable id. A paused
    plan and a paused fleet are separate outcomes and admit nothing; an exhausted backlog is idle,
    never invented work.
    """
    progress = {item["id"]: item_progress(item, intents.get(item["id"]), jobs) for item in plan["items"]}
    ordered = sorted(plan["items"], key=lambda item: (item["priority"], item["id"]))
    views = [progress[item["id"]] for item in ordered]
    if not plan["enabled"]:
        return {"outcome": OUTCOME_PLAN_PAUSED, "item": None, "blocked": {}, "progress": views}
    if fleet_paused:
        return {"outcome": OUTCOME_FLEET_PAUSED, "item": None, "blocked": {}, "progress": views}
    blocked: dict[str, str] = {}
    resumable, eligible = [], []
    for item in ordered:
        view = progress[item["id"]]
        state = view["state"]
        if state == ITEM_OPEN:
            if view["attempts"] >= MAX_ATTEMPTS:
                blocked[item["id"]] = view["reason_code"] or "attempts_exhausted"
            else:
                resumable.append(item)
            continue
        if state in {ITEM_BLOCKED, ITEM_CONFLICT, ITEM_UNKNOWN}:
            blocked[item["id"]] = view["reason_code"] or state
            continue
        if state == ITEM_ENQUEUED:
            continue  # already admitted exactly once; its Fleet row is the authority from here
        reason = next((r for r in (dependency_reason(progress[d]) for d in item["dependencies"]) if r), None)
        if reason is not None:
            blocked[item["id"]] = reason
        else:
            eligible.append(item)
    chosen = next(iter(resumable + eligible), None)
    if chosen is not None:
        outcome = OUTCOME_SELECTED
    elif blocked:
        outcome = OUTCOME_BLOCKED
    else:
        outcome = OUTCOME_EXHAUSTED
    return {"outcome": outcome, "item": chosen, "blocked": blocked, "progress": views}


def item_next_action(view: dict) -> str:
    """The bounded next action for one item; never a command and never an authorization."""
    state, status = view["state"], view["job_status"]
    if state == ITEM_PENDING:
        return "await_selection"
    if state == ITEM_OPEN:
        return "complete_enqueue"
    if state in {ITEM_BLOCKED, ITEM_CONFLICT, ITEM_UNKNOWN}:
        return "owner_review"
    if status == ACCEPTED:
        # An accepted lane operation is implementation evidence; release and deployment are their
        # own owner evidence and are deliberately NOT implied here.
        return "owner_release_decision"
    if status in DEPENDENCY_BLOCKING:
        return "owner_review"
    return "await_fleet"


def plan_next_action(outcome: str) -> str:
    return {OUTCOME_SELECTED: "tick", OUTCOME_BLOCKED: "owner_review", OUTCOME_EXHAUSTED: "idle",
            OUTCOME_PLAN_PAUSED: "enable_plan", OUTCOME_FLEET_PAUSED: "resume_fleet",
            OUTCOME_UNREGISTERED: "register_plan"}.get(outcome, "owner_review")


def plan_status(row: dict, intents: dict, jobs: dict, fleet_paused: bool) -> dict:
    """`urn:zeus:fleet-backlog-status:1`: identities, the pin, states, fixed reason codes and the
    next action. No manifest text, objective, goal text, absolute path, schema or DSN is projected,
    and an absent job is unknown rather than absent work."""
    plan = row["plan"]
    decision = select(plan, intents, jobs, fleet_paused)
    items = [{**view, "next_action": item_next_action(view)} for view in decision["progress"]]
    counts = {state: sum(1 for view in items if view["state"] == state)
              for state in (ITEM_PENDING, ITEM_OPEN, ITEM_ENQUEUED, ITEM_BLOCKED, ITEM_CONFLICT, ITEM_UNKNOWN)}
    counts["accepted"] = sum(1 for view in items if view["job_status"] == ACCEPTED)
    return {"schema": STATUS_SCHEMA, "plan_id": plan["plan_id"], "registered": True,
            "enabled": plan["enabled"], "fleet_paused": bool(fleet_paused),
            "repository": plan["repository"], "plan_sha256": row["plan_sha256"], "pin": dict(row["pin"]),
            "outcome": decision["outcome"], "next_item": None if decision["item"] is None else decision["item"]["id"],
            "next_action": plan_next_action(decision["outcome"]), "blocked": dict(decision["blocked"]),
            "items": items, "counts": counts, "authority": AUTHORITY}


__all__ = ["AUTHORITY", "BLOCKED", "CONFLICT", "ENQUEUED", "FAILED_OUTCOMES", "INTENDED",
           "INTENT_STATES", "ITEM_BLOCKED", "ITEM_CONFLICT", "ITEM_ENQUEUED", "ITEM_OPEN",
           "ITEM_PENDING", "ITEM_UNKNOWN", "MAX_ATTEMPTS", "OPEN_STATES", "OUTCOME_BLOCKED",
           "OUTCOME_CONFLICT", "OUTCOME_ENQUEUED", "OUTCOME_EXHAUSTED", "OUTCOME_FLEET_PAUSED",
           "OUTCOME_PLAN_PAUSED", "OUTCOME_REFUSED", "OUTCOME_SELECTED", "OUTCOME_UNAVAILABLE",
           "OUTCOME_UNREGISTERED", "PLAN_SCHEMA", "SELECTED", "STATUS_SCHEMA", "TICK_SCHEMA",
           "BacklogRefused", "dependency_reason", "intent_key", "intent_pin", "item_next_action",
           "item_pin", "item_progress", "job_matches", "new_intent", "plan_digest",
           "plan_next_action", "plan_status", "reconcile_intent", "select", "validate_pin",
           "validate_plan"]
