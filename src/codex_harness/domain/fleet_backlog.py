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
picked, an admitted item whose portfolio linkage is still pending is completed next, eligible items
are ordered by priority then by stable id, and a blocked or repeatedly unavailable item never
starves another eligible one - it is deferred for a bounded, doubling number of ticks and keeps its
recoverable intent. One item's identity is the COMPLETE `domain.fleet.binding` of its job, so a
partial comparison never settles anything. A selection is an admission intent, never a completion,
a goal acceptance, a review verdict, a release or a deployment receipt.
"""
from __future__ import annotations

import re

from codex_harness.domain.fleet import ACCEPTED, DEPENDENCY_BLOCKING, binding
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
# The whole frozen scope of a selected item: its goal binding and its declared dependency item ids
# beside the pin. Once an intent exists none of this may move - a re-registration that changes any
# of it refuses without mutation, for an open intent and for an admitted one alike.
ITEM_SCOPE_FIELDS = ("project_id", "criterion_id", "lane", "manifest_path", "manifest_revision",
                     "manifest_sha256", "dependencies")
# The fields `domain.fleet.binding` reads. A projection that lacks any of them (`Fleet._view` omits
# `repository`) cannot establish an identity and is never compared as if it could.
BINDING_SOURCE_FIELDS = frozenset({"lane", "manifest_sha256", "repository", "dependencies", "goal"})
GOAL_BINDING_FIELDS = ("path", "sha256", "criterion", "base_revision")

MAX_ITEMS = 64
MAX_DEPENDENCIES = 8
MAX_PRIORITY = 10_000
# Two distinct definite refusals of the same item stop that item and hand it to the owner; a
# transient unavailable input is not an attempt and is not counted here.
MAX_ATTEMPTS = 2
# Repeated unavailability of ONE item's input or of its binding owner: the item is deferred for a
# bounded, doubling number of ticks so an eligible independent item keeps moving, and after
# MAX_DEFERRALS consecutive outages it is handed to the owner instead of being retried forever.
# The deferral is durable, so it survives a restart and is never a discarded intent.
MAX_DEFERRALS = 5
MAX_DEFER_TICKS = 8

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

# The portfolio linkage of an admitted job, recorded by the existing `Portfolio.bind` owner. It is
# durable and separate from admission: a job exists before it is linked, and `pending` is a real
# unfinished state that neither reports linked success nor unlocks a dependent item.
LINK_PENDING, LINK_LINKED, LINK_CONFLICT, LINK_BLOCKED = "pending", "linked", "conflict", "blocked"
LINK_OPEN = frozenset({LINK_PENDING})
LINK_REFUSED = frozenset({LINK_CONFLICT, LINK_BLOCKED})

# What this tick must do for the item it selected: complete the enqueue, or complete the durable
# portfolio linkage of an item whose job already exists.
ACTION_ENQUEUE, ACTION_LINK = "enqueue", "link"

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

# How a RETURNED tick outcome reads to the runner that called it. A tick that answers `unavailable`
# or `refused` is a failure of that tick, exactly like a raised outage: it is never `ok` merely
# because the call returned. Idle, blocked and both pauses are ordinary healthy states.
RUNNER_OK, RUNNER_UNAVAILABLE, RUNNER_REFUSED = "ok", "unavailable", "refused"
RUNNER_STATES = {OUTCOME_UNAVAILABLE: RUNNER_UNAVAILABLE, OUTCOME_REFUSED: RUNNER_REFUSED,
                 OUTCOME_CONFLICT: RUNNER_REFUSED, OUTCOME_UNREGISTERED: RUNNER_REFUSED}

# The fixed structured observation types for these transitions (domain.observation REGISTRY).
# Admission is a development fact; refusal, conflict, unavailability and recovery are operations.
EVENT_ADMITTED = "development.backlog_item_admitted"
EVENT_REFUSED = "operations.backlog_item_refused"
EVENT_UNAVAILABLE = "operations.backlog_unavailable"
EVENT_RECOVERED = "operations.backlog_recovered"

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


def item_scope(item: dict) -> dict:
    """Everything an intent freezes: the goal binding, the lane, the manifest pin and the declared
    dependency item ids."""
    return {key: list(item[key]) if key == "dependencies" else item[key] for key in ITEM_SCOPE_FIELDS}


def intent_scope(intent: dict) -> dict:
    return {key: list(intent.get(key) or []) if key == "dependencies" else intent.get(key)
            for key in ITEM_SCOPE_FIELDS}


def scope_reason(item: dict, intent: dict) -> str | None:
    """None when the plan still says exactly what this intent was selected under, and a fixed code
    otherwise: `pin_changed` when the lane or the manifest pin moved, `scope_changed` when the
    project, criterion or dependency identities did."""
    if intent_scope(intent) == item_scope(item):
        return None
    return "pin_changed" if intent_pin(intent) != item_pin(item) else "scope_changed"


def intent_key(plan_id: str, item_id: str) -> str:
    return plan_id + ":" + item_id


def new_intent(plan_id: str, item: dict, now: str) -> dict:
    """The durable intent row, written BEFORE the pinned input is read and before any enqueue.

    It carries the whole frozen scope - the goal binding (project and criterion), the pin, the lane
    and the declared dependencies - so a restarted or duplicated tick recognizes exactly one
    identity for this item. `job_binding` stays None until the complete Fleet binding this intent
    will enqueue is known; a partial identity never reconciles anything.
    """
    return {"id": intent_key(plan_id, item["id"]), "plan_id": plan_id, "item_id": item["id"],
            **item_scope(item), "state": SELECTED, "job_id": None, "job_manifest_sha256": None,
            "goal_sha256": None, "base_revision": None, "job_binding": None, "attempts": 0,
            "reason_code": None, "error_type": None, "deferrals": 0, "defer_ticks": 0,
            "link_state": LINK_PENDING, "link_reason": None, "linked_at": None,
            "created_at": now, "updated_at": now, "enqueued_at": None}


def expected_binding(lane: str, repository: str, manifest_sha256: str, dependencies, goal: dict) -> dict:
    """The COMPLETE `domain.fleet.binding` identity this intent is about to enqueue.

    `binding` itself decides the shape, and the goal projection is the one `new_job` freezes, so
    the recorded expectation and an authoritative job row are compared field for field: lane,
    repository, manifest digest, predeclared dependencies and every bound goal field.
    """
    return binding({"lane": lane, "manifest_sha256": manifest_sha256, "repository": repository,
                    "dependencies": list(dependencies),
                    "goal": {key: goal[key] for key in GOAL_BINDING_FIELDS}})


def job_binding(job) -> dict | None:
    """The complete binding of an AUTHORITATIVE job row, or None for anything else.

    `Fleet._view` omits `repository`, so a projected row is not silently compared as if it carried
    a whole identity: an incomplete row answers None and can never match.
    """
    if not isinstance(job, dict) or not BINDING_SOURCE_FIELDS <= set(job):
        return None
    return binding(job)


def job_matches(intent: dict, job: dict) -> bool:
    """An already created job is THIS intent's job only when the complete recorded binding - lane,
    repository, frozen manifest digest, dependencies and every bound goal field - is exactly the
    row's own binding. An equal id under any other binding is a conflict, never evidence that the
    enqueue succeeded, and an intent without a recorded binding proves nothing at all."""
    recorded = intent.get("job_binding")
    if not isinstance(recorded, dict) or job.get("id") != intent.get("job_id"):
        return False
    return job_binding(job) == recorded


def defer_ticks_for(deferrals: int) -> int:
    """The bounded doubling backoff of one item after `deferrals` consecutive outages."""
    return min(2 ** max(0, deferrals - 1), MAX_DEFER_TICKS)


def deferred(intent) -> bool:
    return int((intent or {}).get("defer_ticks") or 0) > 0


def link_state(intent) -> str:
    state = (intent or {}).get("link_state")
    return state if state in {LINK_PENDING, LINK_LINKED, LINK_CONFLICT, LINK_BLOCKED} else LINK_PENDING


def runner_state(outcome) -> str:
    """What a RETURNED tick outcome means to the runner: `ok`, `unavailable` or `refused`."""
    return RUNNER_STATES.get(outcome, RUNNER_OK)


def safe_error_type(value) -> str | None:
    """An exception TYPE name and nothing else; any other text is `unknown` rather than relayed."""
    if value is None:
        return None
    return value if _token(value) else "unknown"


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
    status of its job when there is one, its portfolio linkage and a fixed reason code. Missing
    evidence is unknown."""
    view = {"item_id": item["id"], "project_id": item["project_id"], "criterion_id": item["criterion_id"],
            "lane": item["lane"], "priority": item["priority"],
            "pin": {"revision": item["manifest_revision"], "sha256": item["manifest_sha256"],
                    "path": item["manifest_path"]},
            "dependencies": list(item["dependencies"]), "job_id": None, "job_status": None,
            "reason_code": None, "attempts": 0, "deferrals": 0, "link_state": LINK_PENDING,
            "link_reason": None}
    if intent is None:
        return {**view, "state": ITEM_PENDING}
    view = {**view, "job_id": intent.get("job_id"), "attempts": intent.get("attempts", 0),
            "deferrals": int(intent.get("deferrals") or 0), "reason_code": intent.get("reason_code"),
            "link_state": link_state(intent), "link_reason": intent.get("link_reason")}
    moved = scope_reason(item, intent)
    if moved is not None:
        # The plan moved under an item that already has a durable identity: refuse, never rebind.
        return {**view, "state": ITEM_CONFLICT, "reason_code": moved}
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
    """None when a dependency is satisfied - its Fleet job is `accepted` AND its durable portfolio
    linkage is complete - and a fixed code otherwise. A failed, unlinked or conflicted dependency
    blocks its dependents only; it starves nothing else."""
    state = progress["state"]
    if state == ITEM_ENQUEUED:
        if progress["job_status"] == ACCEPTED:
            # Incomplete or refused linkage never unlocks a successor: the goal binding of the work
            # that just finished is not yet proved to exist.
            return None if progress["link_state"] == LINK_LINKED else "dependency_unlinked"
        if progress["job_status"] in DEPENDENCY_BLOCKING:
            return "dependency_" + progress["job_status"]
        return "dependency_waiting"
    if state in {ITEM_CONFLICT, ITEM_BLOCKED, ITEM_UNKNOWN}:
        return "dependency_" + state
    return "dependency_waiting"


def select(plan: dict, intents: dict, jobs: dict, fleet_paused: bool = False) -> dict:
    """The one item this tick may work on, what it must do with it, and why every other item waits.

    Order: open durable intents first (an interrupted enqueue is completed before new work is
    admitted), then admitted items whose durable portfolio linkage is still pending, then
    dependency-satisfied pending items by priority and then by stable id. An item whose input or
    binding owner was repeatedly unavailable is DEFERRED for a bounded number of ticks: it keeps
    its intent, stays visible and recoverable, and stops starving an eligible independent item.
    `deferred` lists exactly the items this decision passed over that way, so the caller can count
    their bounded wait down durably. A paused plan and a paused fleet are separate outcomes and
    admit nothing; an exhausted backlog is idle, never invented work.
    """
    progress = {item["id"]: item_progress(item, intents.get(item["id"]), jobs) for item in plan["items"]}
    ordered = sorted(plan["items"], key=lambda item: (item["priority"], item["id"]))
    views = [progress[item["id"]] for item in ordered]
    idle = {"item": None, "action": None, "blocked": {}, "deferred": [], "progress": views}
    if not plan["enabled"]:
        return {**idle, "outcome": OUTCOME_PLAN_PAUSED}
    if fleet_paused:
        return {**idle, "outcome": OUTCOME_FLEET_PAUSED}
    blocked: dict[str, str] = {}
    deferred_items: list[str] = []
    resumable, relinkable, eligible = [], [], []
    for item in ordered:
        item_id, view = item["id"], progress[item["id"]]
        intent, state = intents.get(item_id), view["state"]
        if state == ITEM_OPEN:
            if view["attempts"] >= MAX_ATTEMPTS:
                blocked[item_id] = view["reason_code"] or "attempts_exhausted"
            elif deferred(intent):
                blocked[item_id] = "deferred_" + (view["reason_code"] or "unavailable")
                deferred_items.append(item_id)
            else:
                resumable.append(item)
            continue
        if state in {ITEM_BLOCKED, ITEM_CONFLICT, ITEM_UNKNOWN}:
            blocked[item_id] = view["reason_code"] or state
            continue
        if state == ITEM_ENQUEUED:
            # Admitted exactly once; its Fleet row is the authority from here. What may still be
            # owed is the durable portfolio linkage of that job.
            if view["link_state"] == LINK_LINKED:
                continue
            if view["link_state"] in LINK_REFUSED:
                blocked[item_id] = view["link_reason"] or view["link_state"]
            elif deferred(intent):
                blocked[item_id] = "deferred_" + (view["link_reason"] or "binding_pending")
                deferred_items.append(item_id)
            else:
                relinkable.append(item)
            continue
        reason = next((r for r in (dependency_reason(progress[d]) for d in item["dependencies"]) if r), None)
        if reason is not None:
            blocked[item_id] = reason
        else:
            eligible.append(item)
    chosen = next(iter(resumable + relinkable + eligible), None)
    relink = {item["id"] for item in relinkable}
    if chosen is not None:
        outcome = OUTCOME_SELECTED
    elif blocked:
        outcome = OUTCOME_BLOCKED
    else:
        outcome = OUTCOME_EXHAUSTED
    return {"outcome": outcome, "item": chosen, "blocked": blocked, "progress": views,
            "deferred": deferred_items,
            "action": None if chosen is None else (ACTION_LINK if chosen["id"] in relink else ACTION_ENQUEUE)}


def item_next_action(view: dict) -> str:
    """The bounded next action for one item; never a command and never an authorization."""
    state, status = view["state"], view["job_status"]
    if state == ITEM_PENDING:
        return "await_selection"
    if state == ITEM_OPEN:
        return "complete_enqueue"
    if state in {ITEM_BLOCKED, ITEM_CONFLICT, ITEM_UNKNOWN}:
        return "owner_review"
    if view["link_state"] in LINK_REFUSED:
        return "owner_review"
    if view["link_state"] != LINK_LINKED:
        # The job exists; its goal binding does not yet. That is unfinished work, never a release.
        return "complete_binding"
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
    # Admitted work whose goal binding is not yet proved: counted apart from `enqueued` so an
    # incomplete linkage is never read as finished admission.
    counts["unlinked"] = sum(1 for view in items
                             if view["state"] == ITEM_ENQUEUED and view["link_state"] != LINK_LINKED)
    return {"schema": STATUS_SCHEMA, "plan_id": plan["plan_id"], "registered": True,
            "enabled": plan["enabled"], "fleet_paused": bool(fleet_paused),
            "repository": plan["repository"], "plan_sha256": row["plan_sha256"], "pin": dict(row["pin"]),
            "outcome": decision["outcome"], "next_item": None if decision["item"] is None else decision["item"]["id"],
            "next_action": plan_next_action(decision["outcome"]), "blocked": dict(decision["blocked"]),
            "items": items, "counts": counts, "authority": AUTHORITY}


__all__ = ["ACTION_ENQUEUE", "ACTION_LINK", "AUTHORITY", "BLOCKED", "CONFLICT", "ENQUEUED",
           "EVENT_ADMITTED", "EVENT_RECOVERED", "EVENT_REFUSED", "EVENT_UNAVAILABLE",
           "FAILED_OUTCOMES", "INTENDED", "INTENT_STATES", "ITEM_BLOCKED", "ITEM_CONFLICT",
           "ITEM_ENQUEUED", "ITEM_OPEN", "ITEM_PENDING", "ITEM_UNKNOWN", "LINK_BLOCKED",
           "LINK_CONFLICT", "LINK_LINKED", "LINK_PENDING", "LINK_REFUSED", "MAX_ATTEMPTS",
           "MAX_DEFERRALS", "MAX_DEFER_TICKS", "OPEN_STATES", "OUTCOME_BLOCKED", "OUTCOME_CONFLICT",
           "OUTCOME_ENQUEUED", "OUTCOME_EXHAUSTED", "OUTCOME_FLEET_PAUSED", "OUTCOME_PLAN_PAUSED",
           "OUTCOME_REFUSED", "OUTCOME_SELECTED", "OUTCOME_UNAVAILABLE", "OUTCOME_UNREGISTERED",
           "PLAN_SCHEMA", "RUNNER_OK", "RUNNER_REFUSED", "RUNNER_UNAVAILABLE", "SELECTED",
           "STATUS_SCHEMA", "TICK_SCHEMA", "BacklogRefused", "defer_ticks_for", "deferred",
           "dependency_reason", "expected_binding", "intent_key", "intent_pin", "intent_scope",
           "item_next_action", "item_pin", "item_progress", "item_scope", "job_binding",
           "job_matches", "link_state", "new_intent", "plan_digest", "plan_next_action",
           "plan_status", "reconcile_intent", "runner_state", "safe_error_type", "scope_reason",
           "select", "validate_pin", "validate_plan"]
