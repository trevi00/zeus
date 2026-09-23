"""Durable conductor continuation: the pure policy, routing table and intent lifecycle (INV-CONTINUATION-001).

The controller keeps one logical goal moving across FINITE operations without editing any of them.
It observes a terminal Fleet job (and the bound lane evidence behind it), picks exactly one row of
the fixed routing table below and records a durable intent BEFORE the one effect that row
authorizes. This module decides; it performs no I/O.

| Observed evidence                         | Authorized continuation                   | Completion evidence |
| ----------------------------------------- | ----------------------------------------- | ------------------- |
| failed / evidence_gate_refused, effects known | evidence repair successor, candidate kept | new bound inspection + independent review |
| rejected exact independent review         | correction successor under the same frame  | pinned successor, retained rejection, session lineage |
| two distinct similar failed attempts      | existing Portfolio investigation (research) | owner scoped research receipt (exact attempts) |
| unknown provider / external effects       | existing ExecutionRecovery                 | bound proof; never a fresh call |
| accepted lead candidate                   | existing conductor review (guarded row)    | succeeded conductor decision, Releases record |
| qualified (conductor-accepted) release    | HostDelivery + managed runtime target      | `active` consumption, or verified rollback |
| completed item                            | existing approved backlog selection        | next backlog admission |

What is authoritative, and what is not:

- The owner's Git-pinned policy is the only permission. It binds the lanes, the repository, the
  goals, the allowed paths and acceptance criteria, the session archive root, the qualified model,
  image and profile and the delivery target. A successor manifest keeps the original goal, allowed
  paths and acceptance criteria byte for byte; model output never extends them.
- The intent id is `origin job + generation/attempt + decisive evidence digest + route`, so a
  replayed event, a restart or a second controller derives the SAME intent and the same successor
  id, never a second one. A replay is not another failure. The id carries no policy: a row belongs
  to the policy that wrote it, and another policy never reuses or reports it (`owners`).
- A rejected finite operation stays rejected: the successor is a new operation with lineage.
"""
from __future__ import annotations

import re

from codex_harness.domain.model import ContractError, digest

POLICY_SCHEMA = "urn:zeus:continuation-policy:1"
BINDING_SCHEMA = "urn:zeus:continuation-binding:1"
STATUS_SCHEMA = "urn:zeus:continuation-status:1"
TICK_SCHEMA = "urn:zeus:continuation-tick:1"
AUTHORITY = ("continuation intent projection: not an approval, a review, a merge, a release or a "
             "deployment; each effect is performed by its existing owner")

POLICY_FIELDS = {"schema", "id", "enabled", "repository", "lanes", "goals", "allowed_paths",
                 "acceptance_criteria", "session_archive_sha256", "qualified", "delivery_target",
                 "max_corrections"}
GOAL_FIELDS = {"path", "sha256", "criterion"}
QUALIFIED_FIELDS = {"model", "image", "profile"}
MAX_CORRECTIONS = 8
MAX_ACTIONS_PER_TICK = 4
MAX_HISTORY = 32

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,200}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")

# ---- routes (one per routing-table row) and their existing owners --------------------------------
EVIDENCE_REPAIR = "evidence_repair"
CORRECTION = "correction"
RESEARCH = "research"
RECOVERY = "recovery"
CONDUCTOR = "conductor_review"
DELIVERY = "host_delivery"
NEXT_ITEM = "next_item"
ROUTES = (EVIDENCE_REPAIR, CORRECTION, RESEARCH, RECOVERY, CONDUCTOR, DELIVERY, NEXT_ITEM)
SUCCESSOR_ROUTES = frozenset({EVIDENCE_REPAIR, CORRECTION})
FAILURE_ROUTES = SUCCESSOR_ROUTES
ROUTE_OWNERS = {EVIDENCE_REPAIR: "fleet", CORRECTION: "fleet", RESEARCH: "portfolio_research",
                RECOVERY: "execution_recovery", CONDUCTOR: "conductor", DELIVERY: "host_delivery",
                NEXT_ITEM: "fleet_backlog"}
ROUTE_COMPLETION = {EVIDENCE_REPAIR: "new bound inspection and independent review of the successor",
                    CORRECTION: "pinned successor with retained rejection and session lineage",
                    RESEARCH: "owner scoped research receipt covering the exact family attempts, an accepted "
                              "research dispatch and immutable evidence before another correction",
                    RECOVERY: "bound reconciliation proof; no fresh invocation",
                    CONDUCTOR: "succeeded conductor decision and its Releases record",
                    DELIVERY: "active consumption receipt or verified predecessor rollback",
                    NEXT_ITEM: "next approved backlog item admitted by its owner"}

# ---- intent states: pre-effect intent, publication, admission, returned effect, reconciliation ---
INTENDED = "intended"          # durable, nothing external done yet
PUBLISHED = "published"        # successor binding written to the lane store (idempotent document)
ADMITTED = "admitted"          # the existing Fleet admitted the successor job (same id on replay)
DISPATCHED = "dispatched"      # conductor child launched under this intent (never relaunched blindly)
RETURNED = "returned"          # the effect's own terminal evidence was observed
AWAITING_OWNER = "awaiting_owner"
RESEARCH_REQUIRED = "research_required"
RECOVERY_REQUIRED = "recovery_required"
PAUSED = "paused"              # the family is held (release rejection / rollback); acceptance kept
REFUSED = "refused"
COMPLETED = "completed"
STATES = (INTENDED, PUBLISHED, ADMITTED, DISPATCHED, RETURNED, AWAITING_OWNER, RESEARCH_REQUIRED,
          RECOVERY_REQUIRED, PAUSED, REFUSED, COMPLETED)
TRANSITIONS = {
    None: frozenset({INTENDED, RESEARCH_REQUIRED, RECOVERY_REQUIRED, REFUSED, AWAITING_OWNER}),
    INTENDED: frozenset({PUBLISHED, DISPATCHED, AWAITING_OWNER, REFUSED, RECOVERY_REQUIRED, COMPLETED, PAUSED}),
    PUBLISHED: frozenset({ADMITTED, REFUSED}),
    ADMITTED: frozenset({RETURNED}),
    DISPATCHED: frozenset({RETURNED, RECOVERY_REQUIRED, AWAITING_OWNER}),
    RETURNED: frozenset({COMPLETED}),
    AWAITING_OWNER: frozenset({INTENDED, COMPLETED, PAUSED, RECOVERY_REQUIRED, REFUSED}),
    RESEARCH_REQUIRED: frozenset({COMPLETED}),
    RECOVERY_REQUIRED: frozenset(),
    PAUSED: frozenset(),
    REFUSED: frozenset(),
    COMPLETED: frozenset(),
}
OPEN_STATES = frozenset({INTENDED, PUBLISHED, ADMITTED, DISPATCHED, RETURNED, AWAITING_OWNER, RESEARCH_REQUIRED})
# A family with one of these holds its lineage: no further successor is derived for it, while every
# other family keeps being selected.
BLOCKING_STATES = frozenset({RESEARCH_REQUIRED, RECOVERY_REQUIRED, PAUSED, REFUSED})

# ---- route x state restart table ----------------------------------------------------------------
# Every durable boundary a route can leave behind, and the ONE thing a restarted (or second)
# controller does with it. A row absent here is terminal. `dispatch` and `publish` are NEW effects
# and pass the eligibility guard first; `reconcile_launch` only observes an effect already started.
PUBLISH, AWAIT_SUCCESSOR, COMPLETE = "publish", "await_successor", "complete"
DISPATCH, RECONCILE_LAUNCH, REDISPATCH = "dispatch", "reconcile_launch", "redispatch"
OBSERVE_DELIVERY, OBSERVE_RESEARCH, AWAIT_BACKLOG = "observe_delivery", "observe_research", "await_backlog"
RESUME = {
    **{(route, state): action for route in (EVIDENCE_REPAIR, CORRECTION)
       for state, action in ((INTENDED, PUBLISH), (PUBLISHED, PUBLISH), (ADMITTED, AWAIT_SUCCESSOR),
                             (RETURNED, COMPLETE))},
    (CONDUCTOR, INTENDED): DISPATCH,
    (CONDUCTOR, DISPATCHED): RECONCILE_LAUNCH,
    (CONDUCTOR, RETURNED): COMPLETE,
    (CONDUCTOR, AWAITING_OWNER): REDISPATCH,
    (DELIVERY, AWAITING_OWNER): OBSERVE_DELIVERY,
    (RESEARCH, RESEARCH_REQUIRED): OBSERVE_RESEARCH,
    (NEXT_ITEM, AWAITING_OWNER): AWAIT_BACKLOG,
}
# The states each route can durably hold; the open ones are exactly the RESUME rows of that route.
ROUTE_STATES = {EVIDENCE_REPAIR: (INTENDED, PUBLISHED, ADMITTED, RETURNED, COMPLETED, REFUSED),
                CORRECTION: (INTENDED, PUBLISHED, ADMITTED, RETURNED, COMPLETED, REFUSED),
                CONDUCTOR: (INTENDED, DISPATCHED, RETURNED, AWAITING_OWNER, COMPLETED, RECOVERY_REQUIRED,
                            REFUSED),
                DELIVERY: (AWAITING_OWNER, COMPLETED, PAUSED, REFUSED),
                RESEARCH: (RESEARCH_REQUIRED, COMPLETED),
                RECOVERY: (RECOVERY_REQUIRED,),
                NEXT_ITEM: (AWAITING_OWNER,)}

# ---- conductor launches: owned child identity ---------------------------------------------------
# What reconciliation observed about one launch: still running (owned here or by an unknown owner),
# exited (with or without its receipt), proven never started (fenced), timed out and ended by its
# owner, or not determinable. Only `absent` permits another launch, and only of a NEW identity.
LAUNCH_RUNNING, LAUNCH_EXITED, LAUNCH_ABSENT = "running", "exited", "absent"
LAUNCH_TIMEOUT, LAUNCH_UNKNOWN = "timeout", "unknown"
LAUNCH_STATES = (LAUNCH_RUNNING, LAUNCH_EXITED, LAUNCH_ABSENT, LAUNCH_TIMEOUT, LAUNCH_UNKNOWN)
# At most this many launch identities per conductor intent; each one enters the guarded claim at
# most once, so this bounds process starts, never model calls (the expected-row guard bounds those).
MAX_LAUNCHES = 3


def launch_id(intent: str, sequence: int) -> str:
    """Deterministic launch identity: a restart or a second controller names the SAME launch."""
    return digest(["conductor_launch", intent, sequence])

# Terminal lane-operation reasons whose provider/process/publication effects are NOT known.
UNKNOWN_EFFECT_REASONS = frozenset({"settlement_failed", "collection_failed", "publication_incomplete",
                                    "no_terminal_outcome", "acceptance_unproven", "review_verdict_unknown",
                                    "spawn_uncertain", "outcome_uncertain", "in_flight_residue"})


class ContinuationRefused(ContractError):
    """A refusal with a fixed reason code and the named owner who must act next."""

    def __init__(self, reason_code: str, owner: str = "operator", field: str | None = None):
        super().__init__("continuation refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.owner, self.field = reason_code, owner, field


def refuse(condition, reason_code: str, owner: str = "operator", field: str | None = None) -> None:
    if not condition:
        raise ContinuationRefused(reason_code, owner, field)


def transition(current, target: str) -> str:
    refuse(target in TRANSITIONS.get(current, frozenset()), "invalid_transition", field=f"{current}->{target}")
    return target


# ---- policy -------------------------------------------------------------------------------------
def _text_list(value, limit: int, item_limit: int) -> bool:
    return (isinstance(value, list) and 0 < len(value) <= limit and len(set(value)) == len(value)
            and all(type(v) is str and 0 < len(v.strip()) <= item_limit for v in value))


def _fields(document, expected: set, name: str) -> None:
    refuse(isinstance(document, dict) and set(document) == expected, "policy_invalid", field=name)


def validate_policy(document) -> dict:
    """Strict owner policy; returns a canonical copy. Unknown or missing fields are refused."""
    from codex_harness.domain.operation import safe_relative_path

    _fields(document, POLICY_FIELDS, "root")
    refuse(document["schema"] == POLICY_SCHEMA, "policy_invalid", field="schema")
    refuse(type(document["id"]) is str and TOKEN.fullmatch(document["id"]) is not None, "policy_invalid", field="id")
    refuse(type(document["enabled"]) is bool, "policy_invalid", field="enabled")
    refuse(type(document["repository"]) is str and SHA256.fullmatch(document["repository"]) is not None,
           "policy_invalid", field="repository")
    lanes = document["lanes"]
    refuse(isinstance(lanes, list) and 0 < len(lanes) <= 16 and len(set(lanes)) == len(lanes)
           and all(type(lane) is str and TOKEN.fullmatch(lane) for lane in lanes), "policy_invalid", field="lanes")
    goals = document["goals"]
    refuse(isinstance(goals, list) and 0 < len(goals) <= 32, "policy_invalid", field="goals")
    for goal in goals:
        _fields(goal, GOAL_FIELDS, "goals[]")
        refuse(safe_relative_path(goal["path"]) and goal["path"].lower().endswith(".md"), "policy_invalid",
               field="goals[].path")
        refuse(type(goal["sha256"]) is str and SHA256.fullmatch(goal["sha256"]) is not None, "policy_invalid",
               field="goals[].sha256")
        refuse(type(goal["criterion"]) is str and 0 < len(goal["criterion"].strip()) <= 400, "policy_invalid",
               field="goals[].criterion")
    paths = document["allowed_paths"]
    refuse(isinstance(paths, list) and 0 < len(paths) <= 256 and len(set(paths)) == len(paths)
           and all(safe_relative_path(p) for p in paths), "policy_invalid", field="allowed_paths")
    refuse(_text_list(document["acceptance_criteria"], 64, 4000), "policy_invalid", field="acceptance_criteria")
    refuse(type(document["session_archive_sha256"]) is str
           and SHA256.fullmatch(document["session_archive_sha256"]) is not None, "policy_invalid",
           field="session_archive_sha256")
    qualified = document["qualified"]
    _fields(qualified, QUALIFIED_FIELDS, "qualified")
    refuse(type(qualified["model"]) is str and 0 < len(qualified["model"]) <= 100, "policy_invalid",
           field="qualified.model")
    refuse(type(qualified["image"]) is str and IMAGE.fullmatch(qualified["image"]) is not None, "policy_invalid",
           field="qualified.image")
    refuse(type(qualified["profile"]) is str and TOKEN.fullmatch(qualified["profile"]) is not None,
           "policy_invalid", field="qualified.profile")
    refuse(type(document["delivery_target"]) is str and TOKEN.fullmatch(document["delivery_target"]) is not None,
           "policy_invalid", field="delivery_target")
    refuse(type(document["max_corrections"]) is int and 0 < document["max_corrections"] <= MAX_CORRECTIONS,
           "policy_invalid", field="max_corrections")
    return {"schema": POLICY_SCHEMA, "id": document["id"], "enabled": document["enabled"],
            "repository": document["repository"], "lanes": sorted(lanes),
            "goals": sorted(({k: g[k] for k in sorted(GOAL_FIELDS)} for g in goals),
                            key=lambda g: (g["path"], g["criterion"])),
            "allowed_paths": list(paths), "acceptance_criteria": list(document["acceptance_criteria"]),
            "session_archive_sha256": document["session_archive_sha256"],
            "qualified": {k: qualified[k] for k in sorted(QUALIFIED_FIELDS)},
            "delivery_target": document["delivery_target"], "max_corrections": document["max_corrections"]}


def policy_digest(policy: dict) -> str:
    return digest(policy)


def check_membership(policy: dict, job: dict) -> None:
    """The job belongs to the policy: its immutable lane, repository, goal, allowed paths and
    criteria are inside the frame. A non-member is not this policy's work at all - it is never
    selected, read or recorded - so unrelated history cannot occupy a bounded pass."""
    refuse(job.get("lane") in policy["lanes"], "lane_outside_policy", field="lane")
    refuse(job.get("repository") == policy["repository"], "repository_changed", field="repository")
    goal = job.get("goal") or {}
    refuse(any(all(goal.get(k) == g[k] for k in GOAL_FIELDS) for g in policy["goals"]), "goal_changed",
           field="goal")
    manifest = job.get("manifest") or {}
    plan = manifest.get("plan") or {}
    refuse(set(plan.get("allowed_paths") or []) <= set(policy["allowed_paths"]) and plan.get("allowed_paths"),
           "scope_changed", field="allowed_paths")
    refuse(set(plan.get("acceptance_criteria") or []) <= set(policy["acceptance_criteria"])
           and plan.get("acceptance_criteria"), "criteria_changed", field="acceptance_criteria")


def is_member(policy: dict, job: dict) -> bool:
    try:
        check_membership(policy, job)
    except ContinuationRefused:
        return False
    return True


def check_scope(policy: dict, job: dict, runtime: dict) -> None:
    """The origin job is inside the policy frame, and the host still runs the qualified identity.

    Any difference is a named refusal: the continuation never widens its own permission to fit a
    changed goal, scope, model, image, profile or session archive. For a member job the model and
    the runtime identity are current eligibility: a visible refusal or hold, never silence."""
    check_membership(policy, job)
    manifest = job.get("manifest") or {}
    refuse((manifest.get("claude") or {}).get("model") == policy["qualified"]["model"], "model_changed",
           field="claude.model")
    refuse(isinstance(runtime, dict), "runtime_unknown", field="runtime")
    refuse(runtime.get("image") == policy["qualified"]["image"], "image_changed", field="image")
    refuse(runtime.get("profile") == policy["qualified"]["profile"], "profile_changed", field="profile")
    refuse(runtime.get("session_archive_sha256") == policy["session_archive_sha256"], "session_archive_changed",
           field="session_archive")


# ---- stored authorization and the shared eligibility guard ---------------------------------------
RUNTIME_FIELDS = ("image", "profile", "session_archive_sha256")
AUTHORIZATION_REASONS = {"policy_sha256": "policy_changed", "pin_sha256": "policy_changed",
                         "repository": "repository_changed", "lane": "lane_outside_policy",
                         "goal": "goal_changed", "allowed_paths": "scope_changed",
                         "acceptance_criteria": "criteria_changed", "model": "model_changed",
                         "source": "source_changed"}
RUNTIME_REASONS = {"image": "image_changed", "profile": "profile_changed",
                   "session_archive_sha256": "session_archive_changed"}


def authorization(policy_sha256: str, pin_sha256, job: dict, runtime) -> dict:
    """The exact binding an intent was authorized under: pinned policy, frame, model, runtime
    identity and the source job. Identities only; stored on the intent at creation."""
    manifest = job.get("manifest") or {}
    plan = manifest.get("plan") or {}
    goal = job.get("goal") or {}
    return {"policy_sha256": policy_sha256, "pin_sha256": pin_sha256, "repository": job.get("repository"),
            "lane": job.get("lane"), "goal": {key: goal.get(key) for key in sorted(GOAL_FIELDS)},
            "allowed_paths": sorted(plan.get("allowed_paths") or []),
            "acceptance_criteria": sorted(plan.get("acceptance_criteria") or []),
            "model": (manifest.get("claude") or {}).get("model"),
            "runtime": ({key: runtime.get(key) for key in RUNTIME_FIELDS} if isinstance(runtime, dict) else None),
            "source": {"job": job.get("id"), "manifest_sha256": job.get("manifest_sha256"),
                       "status": job.get("status")}}


def check_authorization(stored, current: dict) -> None:
    """The eligibility guard before every NEW effect: the current binding must equal the stored one.

    Drift refuses by the name of the first differing field; the stored authorization is never
    rewritten to fit the current world, and an intent without one (older rows) is unknown."""
    refuse(isinstance(stored, dict), "authorization_unknown", field="authorization")
    for key, reason in AUTHORIZATION_REASONS.items():
        refuse(stored.get(key) == current.get(key), reason, field=key)
    stored_runtime, current_runtime = stored.get("runtime"), current.get("runtime")
    refuse(isinstance(stored_runtime, dict) and isinstance(current_runtime, dict), "runtime_unknown",
           field="runtime")
    for key in RUNTIME_FIELDS:
        refuse(stored_runtime.get(key) == current_runtime.get(key), RUNTIME_REASONS[key], field=key)


# ---- host delivery evidence bound to target and candidate ----------------------------------------
DELIVERY_BOUND, DELIVERY_ABSENT, DELIVERY_AMBIGUOUS = "bound", "absent", "ambiguous"
DELIVERY_STALE, DELIVERY_MISMATCH, DELIVERY_UNKNOWN = "stale", "release_candidate_mismatch", "unknown"


def bind_delivery(rows: list, target, release_id, revision, release) -> dict:
    """The ONE HostDelivery intent of the policy target for this exact release and candidate.

    A plan of another target for the same release is foreign: it never completes nor pauses this
    item. A plan of this target for another revision is stale, two of them ambiguous, a release
    record naming another candidate a mismatch, a missing candidate unknown - each a named wait,
    never a completion or a pause."""
    bound = {"target_id": target, "release_id": release_id, "revision": revision}
    foreign = sum(1 for row in rows if row.get("target_id") != target)
    base = {**bound, "stage": None, "plan_id": None, "plan_sha256": None, "foreign": foreign}
    if not (isinstance(revision, str) and REVISION.fullmatch(revision)):
        return {**base, "binding": DELIVERY_UNKNOWN}
    candidate = ((release or {}).get("candidate") or {}).get("revision") if isinstance(release, dict) else None
    if release is not None and candidate != revision:
        return {**base, "binding": DELIVERY_MISMATCH}
    mine = [row for row in rows if row.get("target_id") == target]
    exact = [row for row in mine if row.get("revision") == revision]
    if not mine:
        return {**base, "binding": DELIVERY_ABSENT}
    if not exact:
        return {**base, "binding": DELIVERY_STALE}
    if len(exact) > 1:
        return {**base, "binding": DELIVERY_AMBIGUOUS}
    row = exact[0]
    return {**base, "binding": DELIVERY_BOUND, "stage": row.get("stage"), "plan_id": row.get("plan_id") or row.get("id"),
            "plan_sha256": row.get("plan_sha256")}


def delivery_tuple(delivery: dict) -> dict:
    return {key: (delivery or {}).get(key) for key in ("target_id", "release_id", "revision")}


# ---- classification of one terminal observation --------------------------------------------------
def classify(job: dict, evidence: dict) -> dict:
    """The routing-table row for one terminal Fleet job and its lane evidence.

    `evidence` is what the application read from the lane store (outside any transaction):
    `operation` (the lane operations row or None), `markers` (unresolved termination markers of its
    executions), `lead` (the review decision row), `conductor` (the conductor decision row, if any),
    `delivery` (the host delivery intent of the release, if any). Missing evidence is a refusal with
    the owner who can supply it, never a guess."""
    status = job.get("status")
    operation = evidence.get("operation")
    if status == "unknown" or evidence.get("markers"):
        return {"route": RECOVERY, "reason_code": "unknown_effects"}
    if status in {"queued", "dispatching"}:
        return {"route": None, "reason_code": "not_terminal"}
    if operation is None:
        return {"route": None, "reason_code": "lane_evidence_missing", "owner": "operator"}
    reason = operation.get("reason_code") if type(operation.get("reason_code")) is str else "unknown"
    head = reason.split(":", 1)[0]
    if status == "failed" and (head == "exception" or reason in UNKNOWN_EFFECT_REASONS):
        return {"route": RECOVERY, "reason_code": "unknown_effects"}
    if status == "failed" and reason == "evidence_gate_refused":
        handoff = operation.get("owner_handoff") or {}
        candidate = handoff.get("candidate") or {}
        if not (handoff.get("task_id") and REVISION.fullmatch(str(candidate.get("revision") or ""))):
            return {"route": None, "reason_code": "handoff_incomplete", "owner": "lead:improvement"}
        return {"route": EVIDENCE_REPAIR, "reason_code": reason}
    if status == "rejected":
        lead = evidence.get("lead")
        if not (isinstance(lead, dict) and lead.get("status") == "succeeded" and lead.get("phase") == "review_lead"
                and (lead.get("result") or {}).get("accepted") is False):
            return {"route": None, "reason_code": "review_unproven", "owner": "lead:improvement"}
        return {"route": CORRECTION, "reason_code": "lead_rejected"}
    if status == "accepted":
        conductor = evidence.get("conductor")
        if not isinstance(conductor, dict) or conductor.get("status") in {"pending", "retry", None}:
            return {"route": CONDUCTOR, "reason_code": "lead_accepted"}
        if conductor.get("status") == "running":
            return {"route": None, "reason_code": "conductor_running", "owner": "conductor"}
        if conductor.get("status") != "succeeded":
            return {"route": RECOVERY, "reason_code": "conductor_" + str(conductor.get("status"))}
        if (conductor.get("result") or {}).get("accepted") is False:
            return {"route": CORRECTION, "reason_code": "conductor_rejected"}
        return {"route": DELIVERY, "reason_code": "conductor_accepted"}
    if status in {"failed", "exhausted"}:
        return {"route": None, "reason_code": "operation_" + head, "owner": "operator"}
    return {"route": None, "reason_code": "status_unknown", "owner": "operator"}


def evidence_digest(job: dict, evidence: dict, route: str) -> str:
    """The decisive evidence of one observation: identities and verdicts only, never text."""
    operation = evidence.get("operation") or {}
    decisive = {"job": job.get("id"), "status": job.get("status"), "manifest_sha256": job.get("manifest_sha256"),
                "route": route, "operation": {k: operation.get(k) for k in ("status", "reason_code", "task_id",
                                                                             "decision_id")}}
    if route == EVIDENCE_REPAIR:
        handoff = operation.get("owner_handoff") or {}
        decisive["handoff"] = {"id": handoff.get("id"), "inspection": (handoff.get("inspection") or {}).get("id")}
    if route in {CORRECTION, CONDUCTOR, DELIVERY}:
        for key in ("lead", "conductor"):
            row = evidence.get(key) or {}
            decisive[key] = {"id": row.get("id"), "status": row.get("status"),
                             "accepted": (row.get("result") or {}).get("accepted"),
                             "execution_ref": (row.get("result") or {}).get("execution_ref")}
    return digest(decisive)


def attempt_of(evidence: dict) -> dict:
    task = evidence.get("task") or {}
    return {"generation": task.get("generation") if type(task.get("generation")) is int else 0,
            "attempt": task.get("attempt") if type(task.get("attempt")) is int else 0}


def intent_id(origin_job: str, attempt: dict, evidence_sha256: str, route: str) -> str:
    return digest(["continuation_intent", origin_job, attempt["generation"], attempt["attempt"],
                   evidence_sha256, route])


def successor_id(intent: str) -> str:
    """Deterministic, grammar-valid operation/job id: an ACK loss reuses the same successor."""
    return "cont-" + intent[:24]


# ---- effect ownership across policies sharing one control store ----------------------------------
# The intent id is global (no policy in it), so two overlapping policies derive the SAME effect and
# the same successor id. A row stays with the policy that wrote it; another policy never replays,
# advances or reports it. The only foreign row that owns nothing is a refusal written at creation
# (no successor, no launch, no later state): it never authorized an effect, so the next slot of the
# same observation - again derived without the policy - is claimable. Every policy walks the same
# slots, so restarts and concurrent controllers converge on one owner and one successor.
MAX_SLOTS = 8


def intent_slot(key: str, n: int) -> str:
    return key if n == 0 else digest(["continuation_intent_slot", key, n])


def effect_free(row: dict) -> bool:
    return (row.get("state") == REFUSED and row.get("successor_job") is None and row.get("launch") is None
            and [entry.get("state") for entry in row.get("history") or []] == [REFUSED])


def owners(intents: list, policy_id: str) -> dict:
    """job id -> the other policy whose effect-owning intent routed it or created it as a successor.
    Such a job belongs to that lineage: it is excluded before fair selection, never re-observed."""
    mine, out = set(), {}
    for row in intents:
        jobs = [job for job in (row.get("origin_job"), row.get("successor_job")) if job]
        if row.get("policy_id") == policy_id:
            mine.update(jobs)
        elif not effect_free(row):
            for job in jobs:
                out.setdefault(job, row.get("policy_id"))
    return {job: owner for job, owner in out.items() if job not in mine}


# ---- two-strike ---------------------------------------------------------------------------------
def prior_failures(intents: list, family: str) -> list:
    """Distinct failure observations of one family since its last researched diagnosis.

    Only intents with a successor route count, each once (they are keyed by evidence); a replayed
    event maps to the SAME intent and so never counts twice."""
    rows = sorted((row for row in intents if row.get("family") == family), key=lambda r: (r["created_at"], r["id"]))
    counted: list = []
    for row in rows:
        if row["route"] == RESEARCH and row["state"] == COMPLETED:
            counted = []
        elif row["route"] in FAILURE_ROUTES and row["state"] != REFUSED:
            counted.append(row["evidence_sha256"])
    return sorted(set(counted))


def needs_research(intents: list, family: str, evidence_sha256: str) -> bool:
    prior = [ref for ref in prior_failures(intents, family) if ref != evidence_sha256]
    return len(prior) >= 1


# ---- scoped research completion (SPEC "Scoped research completion and evidence-repair delivery") --
# A research hold is released ONLY by an explicit owner receipt naming this exact intent, policy and
# family, the COMPLETE failed attempt set the hold was raised on, the Portfolio investigation holding
# those jobs, the resolved and accepted existing research dispatch (bound run and manifest) and
# immutable evidence references. A coarse `researched` disposition of a same-reason row is evidence
# that the owner looked, never approval for these attempts. The receipt is not an operation
# acceptance, a repair verdict or a promotion.
RESEARCH_RECEIPT_SCHEMA = "urn:zeus:continuation-research-receipt:1"
RECEIPT_FIELDS = {"schema", "intent_id", "policy_id", "policy_sha256", "family", "attempts", "investigation",
                  "dispatch", "evidence_refs"}
RECEIPT_ATTEMPT_FIELDS = {"job", "evidence_sha256", "inspection"}
RECEIPT_DISPATCH_FIELDS = {"program", "run_id", "manifest_sha256", "snapshot_sha256"}
RECEIPT_AUTHORITY = ("owner scoped research completion for one continuation intent: not an operation "
                     "acceptance, a repair verdict, an incident resolution or a promotion")
MAX_RECEIPT_ATTEMPTS, MAX_RECEIPT_REFS = 32, 16
EVIDENCE_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
INVESTIGATION_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RESEARCH_ACCEPTED = "accepted"


def _receipt(condition, field: str) -> None:
    refuse(condition, "research_receipt_invalid", "operator", field)


def validate_research_receipt(document) -> dict:
    """Strict owner receipt; returns the canonical copy (attempts sorted by job). Unknown or missing
    fields, a non content-addressed evidence reference or a duplicate attempt are refused."""
    _receipt(isinstance(document, dict) and set(document) == RECEIPT_FIELDS, "root")
    _receipt(document["schema"] == RESEARCH_RECEIPT_SCHEMA, "schema")
    _receipt(type(document["intent_id"]) is str and SHA256.fullmatch(document["intent_id"]) is not None, "intent_id")
    _receipt(type(document["policy_id"]) is str and TOKEN.fullmatch(document["policy_id"]) is not None, "policy_id")
    _receipt(type(document["policy_sha256"]) is str and SHA256.fullmatch(document["policy_sha256"]) is not None,
             "policy_sha256")
    _receipt(type(document["family"]) is str and TOKEN.fullmatch(document["family"]) is not None, "family")
    attempts = document["attempts"]
    _receipt(isinstance(attempts, list) and 0 < len(attempts) <= MAX_RECEIPT_ATTEMPTS, "attempts")
    for attempt in attempts:
        _receipt(isinstance(attempt, dict) and set(attempt) == RECEIPT_ATTEMPT_FIELDS, "attempts[]")
        _receipt(type(attempt["job"]) is str and TOKEN.fullmatch(attempt["job"]) is not None, "attempts[].job")
        _receipt(type(attempt["evidence_sha256"]) is str and SHA256.fullmatch(attempt["evidence_sha256"]) is not None,
                 "attempts[].evidence_sha256")
        _receipt(attempt["inspection"] is None or (type(attempt["inspection"]) is str
                                                   and TOKEN.fullmatch(attempt["inspection"]) is not None),
                 "attempts[].inspection")
    _receipt(len({a["job"] for a in attempts}) == len(attempts), "attempts[].job")
    _receipt(type(document["investigation"]) is str and INVESTIGATION_REF.fullmatch(document["investigation"]),
             "investigation")
    dispatch = document["dispatch"]
    _receipt(isinstance(dispatch, dict) and set(dispatch) == RECEIPT_DISPATCH_FIELDS, "dispatch")
    _receipt(type(dispatch["program"]) is str and TOKEN.fullmatch(dispatch["program"]) is not None, "dispatch.program")
    _receipt(type(dispatch["run_id"]) is str and TOKEN.fullmatch(dispatch["run_id"]) is not None, "dispatch.run_id")
    for key in ("manifest_sha256", "snapshot_sha256"):
        _receipt(type(dispatch[key]) is str and SHA256.fullmatch(dispatch[key]) is not None, "dispatch." + key)
    refs = document["evidence_refs"]
    _receipt(isinstance(refs, list) and 0 < len(refs) <= MAX_RECEIPT_REFS and len(set(refs)) == len(refs)
             and all(type(ref) is str and EVIDENCE_REF.fullmatch(ref) for ref in refs), "evidence_refs")
    return {"schema": RESEARCH_RECEIPT_SCHEMA, "intent_id": document["intent_id"], "policy_id": document["policy_id"],
            "policy_sha256": document["policy_sha256"], "family": document["family"],
            "attempts": sorted(({k: a[k] for k in sorted(RECEIPT_ATTEMPT_FIELDS)} for a in attempts),
                               key=lambda a: a["job"]),
            "investigation": document["investigation"],
            "dispatch": {k: dispatch[k] for k in sorted(RECEIPT_DISPATCH_FIELDS)}, "evidence_refs": sorted(refs)}


def research_attempts(intents: list, research: dict) -> list:
    """The COMPLETE failed attempt set a research intent holds: the family's distinct failure
    observations of the same policy since its last completed research (the rows `prior_failures`
    counted when the hold was raised), plus the research intent's own observation. Derived from the
    durable rows only, so a replay, a restart and a second controller derive the same set."""
    mark = (str(research.get("created_at")), research["id"])
    rows = sorted((row for row in intents if row.get("family") == research.get("family")
                   and row.get("policy_id") == research.get("policy_id")
                   and (str(row.get("created_at")), row["id"]) < mark),
                  key=lambda r: (str(r.get("created_at")), r["id"]))
    counted: set = set()
    for row in rows:
        if row["route"] == RESEARCH and row["state"] == COMPLETED:
            counted = set()
        elif row["route"] in FAILURE_ROUTES and row["state"] != REFUSED:
            counted.add((row["origin_job"], row["evidence_sha256"]))
    counted.add((research["origin_job"], research["evidence_sha256"]))
    return [{"job": job, "evidence_sha256": sha} for job, sha in sorted(counted)]


def observed_attempt(job: dict, evidence: dict) -> dict:
    """What the lane evidence of one attempt shows NOW: its decisive evidence digest under the
    route it classifies to, and the inspection its owner handoff names (None when it has none)."""
    route = classify(job, evidence).get("route")
    handoff = (evidence.get("operation") or {}).get("owner_handoff") or {}
    inspection = (handoff.get("inspection") or {}).get("id") if isinstance(handoff, dict) else None
    return {"evidence_sha256": evidence_digest(job, evidence, route) if route in FAILURE_ROUTES else None,
            "inspection": inspection if type(inspection) is str else None}


def check_research_receipt(receipt: dict, *, intent, attempts: list, policy, jobs: dict, observed: dict,
                           investigation, dispatch, run_result) -> None:
    """Every binding of one owner receipt against authoritative reads; the first gap refuses by name.

    `intent` is the stored research intent, `attempts` its current `research_attempts`, `policy` the
    registered policy row, `jobs` the Fleet rows of the attempts, `observed` job -> `observed_attempt`
    from the lane (absent: unread), `investigation` the Portfolio row, `dispatch` the research
    dispatch row keyed by that investigation and `run_result` the existing `council_result` over its
    bound run row. Unknown, unavailable, partial, foreign or stale evidence never approves."""
    research = ROUTE_OWNERS[RESEARCH]
    refuse(isinstance(intent, dict), "research_intent_unknown", "operator", "intent_id")
    refuse(isinstance(policy, dict) and intent.get("policy_id") == receipt["policy_id"] == policy.get("id")
           and receipt["policy_sha256"] == intent.get("policy_sha256") == policy.get("policy_sha256"),
           "research_policy_foreign", "operator", "policy")
    refuse(intent.get("route") == RESEARCH, "research_intent_wrong", "operator", "intent_id")
    refuse(intent.get("state") == RESEARCH_REQUIRED, "research_intent_not_held", "operator", "intent_id")
    refuse(receipt["family"] == intent.get("family"), "research_family_mismatch", "operator", "family")
    claimed = {(a["job"], a["evidence_sha256"]) for a in receipt["attempts"]}
    current = {(a["job"], a["evidence_sha256"]) for a in attempts}
    refuse(not claimed < current, "research_coverage_partial", "operator", "attempts")
    refuse(claimed == current, "research_attempts_changed", "operator", "attempts")
    for attempt in receipt["attempts"]:
        seen = observed.get(attempt["job"])
        refuse(isinstance(jobs.get(attempt["job"]), dict) and isinstance(seen, dict), "research_attempt_unavailable",
               "operator", "attempts[].job")
        refuse(seen["evidence_sha256"] == attempt["evidence_sha256"], "research_attempt_changed", "operator",
               "attempts[].evidence_sha256")
        refuse(seen["inspection"] == attempt["inspection"], "research_inspection_mismatch", "operator",
               "attempts[].inspection")
    members = [a["job"] for a in receipt["attempts"]]
    refuse(isinstance(investigation, dict), "research_investigation_unknown", research, "investigation")
    refuse(investigation.get("id") == receipt["investigation"] and investigation.get("kind", "failure_family")
           == "failure_family", "research_investigation_mismatch", research, "investigation")
    refuse(set(members) <= set(investigation.get("job_ids") or [])
           and all(jobs[job].get("status") == investigation.get("family_status")
                   and jobs[job].get("reason_code") == investigation.get("reason_code") for job in members),
           "research_investigation_membership", research, "investigation")
    refuse(isinstance(dispatch, dict), "research_dispatch_unknown", research, "dispatch")
    bound = receipt["dispatch"]
    refuse(dispatch.get("investigation") == receipt["investigation"] and dispatch.get("kind", "failure_family")
           == "failure_family" and all(dispatch.get(key) == bound[key] for key in RECEIPT_DISPATCH_FIELDS),
           "research_dispatch_mismatch", research, "dispatch")
    refuse(dispatch.get("state") == "resolved", "research_unfinished", research, "dispatch")
    refuse(dispatch.get("result") == RESEARCH_ACCEPTED and (run_result or {}).get("result") == RESEARCH_ACCEPTED,
           "research_not_accepted", research, "dispatch")
    # The dispatch snapshot names at most its job sample; a member outside it is unverifiable here.
    refuse(set(members) <= set(dispatch.get("job_ids") or []), "research_scope_unverified", research, "dispatch")


def receipt_view(row: dict) -> dict:
    """Bounded projection of one stored receipt: what it covers, never who typed what."""
    receipt = row.get("receipt") or {}
    return {"intent_id": row.get("id"), "policy_id": receipt.get("policy_id"), "family": receipt.get("family"),
            "covered_jobs": [a.get("job") for a in receipt.get("attempts") or []],
            "inspections": [a.get("inspection") for a in receipt.get("attempts") or []],
            "investigation": receipt.get("investigation"), "dispatch": receipt.get("dispatch"),
            "evidence_refs": list(receipt.get("evidence_refs") or []), "receipt_sha256": row.get("receipt_sha256"),
            "accepted_at": row.get("accepted_at"), "authority": RECEIPT_AUTHORITY}


# ---- fair selection -----------------------------------------------------------------------------
def blocked_families(intents: list) -> dict:
    """family -> the reason its lineage is held. Only the family is held; others stay selectable."""
    held = {}
    for row in intents:
        if row["state"] in BLOCKING_STATES:
            held.setdefault(row["family"], row.get("reason_code") or row["state"])
        elif row["state"] in OPEN_STATES and isinstance(row.get("hold"), dict):
            # An open intent the eligibility guard stopped: its family waits for the named owner.
            held.setdefault(row["family"], row["hold"].get("reason_code") or "held")
    return held


def fair_order(candidates: list, intents: list, limit: int | None = MAX_ACTIONS_PER_TICK) -> list:
    """Round robin over families: least recently served family first, then oldest candidate.

    Held families are dropped here, so one blocked family never starves an unrelated one, and at
    most one candidate per family is returned per tick. `limit=None` returns the whole order for a
    caller that spends its own bounded budget (the tick skips an unavailable lane without a slot,
    and reorders by durable attempt progress, `progress_order`)."""
    held = blocked_families(intents)
    served = {}
    for row in intents:
        served[row["family"]] = max(served.get(row["family"], ""), str(row.get("updated_at") or ""))
    first = {}
    for candidate in sorted(candidates, key=lambda c: (str(c.get("finished_at") or ""), c["job_id"])):
        if candidate["family"] in held or candidate["family"] in first:
            continue
        first[candidate["family"]] = candidate
    return sorted(first.values(), key=lambda c: (served.get(c["family"], ""), str(c.get("finished_at") or ""),
                                                 c["job_id"]))[:limit]


# ---- durable selection progress -----------------------------------------------------------------
# A per-job read failure is not a lane outage, and an unchanged order would pick the SAME failing
# candidates after every tick and restart. Each observation attempt is therefore recorded durably
# BEFORE its lane read, whatever the read then shows; the next pass (any controller) tries the least
# recently attempted candidate first. It records a scheduling attempt only: no intent, verdict or
# evidence. With a fixed finite set of candidates every one is attempted within ceil(n / reads per
# pass) passes.
def progress_order(ordered: list, progress) -> list:
    """`fair_order` output, never-attempted candidates first, then least recently attempted; the
    fair order is kept among equals (the sort is stable)."""
    attempts = (progress or {}).get("attempts") or {}
    return sorted(ordered, key=lambda c: attempts.get(c["job_id"], 0))


def record_attempt(progress, policy_id: str, job_id: str, live, since: int) -> dict:
    """The progress row after one attempt: the stored sequence + 1, never reset by a stale reader.
    Entries of jobs that are no longer candidates are dropped only when they predate the reader's
    snapshot (`since`), so a concurrent controller's newer entry is never lost; the row stays bounded
    by the candidates."""
    progress = progress if isinstance(progress, dict) else {}
    sequence = int(progress.get("sequence") or 0) + 1
    attempts = {job: seq for job, seq in (progress.get("attempts") or {}).items() if job in live or seq > since}
    attempts[job_id] = sequence
    return {"policy_id": policy_id, "sequence": sequence, "attempts": attempts}


# ---- successor ----------------------------------------------------------------------------------
PREFACE = {EVIDENCE_REPAIR: "Evidence repair of the preserved candidate (continuation). Re-run and report "
                            "the declared checks exactly; change code only where a check proves it necessary.",
           CORRECTION: "Correction of the rejected candidate under the same frame (continuation). Address "
                       "every finding of the bound independent review; keep the goal, allowed paths and "
                       "acceptance criteria unchanged."}


def successor_manifest(origin: dict, route: str, successor: str, references: dict) -> dict:
    """The next finite operation: the origin's goal, base, allowed paths, acceptance criteria,
    budget and Claude controls unchanged; only the id and the objective's fixed preface differ.
    `references` are identities and digests only (review/inspection/candidate), never model text."""
    refuse(route in SUCCESSOR_ROUTES, "route_has_no_successor", field="route")
    plan = origin["plan"]
    lines = [PREFACE[route], "Continuation references: " + ", ".join(
        f"{key}={references[key]}" for key in sorted(references) if references[key] is not None)]
    manifest = {"schema": origin["schema"], "id": successor, "base_revision": origin["base_revision"],
                "goal": dict(origin["goal"]),
                "plan": {"objective": "\n".join(lines) + "\n\n" + plan["objective"],
                         "acceptance_criteria": list(plan["acceptance_criteria"]),
                         "allowed_paths": list(plan["allowed_paths"])},
                "budget": dict(origin["budget"]), "claude": dict(origin["claude"])}
    if "design" in origin:
        manifest["design"] = dict(origin["design"])
    return manifest


def validate_binding(document) -> dict:
    """The trusted lane-side continuation binding an Operation claim may attach to its assignment."""
    refuse(isinstance(document, dict) and document.get("schema") == BINDING_SCHEMA, "binding_invalid",
           field="schema")
    refuse(set(document) == {"schema", "operation_id", "policy_sha256", "intent_id", "family", "route",
                             "session", "workspace", "predecessor"}, "binding_invalid", field="fields")
    refuse(type(document["operation_id"]) is str and TOKEN.fullmatch(document["operation_id"]) is not None,
           "binding_invalid", field="operation_id")
    refuse(type(document["policy_sha256"]) is str and SHA256.fullmatch(document["policy_sha256"]) is not None,
           "binding_invalid", field="policy_sha256")
    refuse(type(document["family"]) is str and TOKEN.fullmatch(document["family"]) is not None, "binding_invalid",
           field="family")
    refuse(document["intent_id"] is None or (type(document["intent_id"]) is str
                                             and SHA256.fullmatch(document["intent_id"]) is not None),
           "binding_invalid", field="intent_id")
    refuse(document["route"] in (None, *SUCCESSOR_ROUTES), "binding_invalid", field="route")
    session = document["session"]
    refuse(session is None or (isinstance(session, dict) and set(session) == {"task_id", "repository"}
                               and all(type(session[k]) is str and TOKEN.fullmatch(session[k]) for k in session)),
           "binding_invalid", field="session")
    workspace = document["workspace"]
    refuse(workspace is None or (isinstance(workspace, dict) and set(workspace) == {"origin_task_id", "head", "base"}
                                 and type(workspace["origin_task_id"]) is str
                                 and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", workspace["origin_task_id"])
                                 and REVISION.fullmatch(str(workspace["head"]))
                                 and REVISION.fullmatch(str(workspace["base"]))),
           "binding_invalid", field="workspace")
    refuse(document["predecessor"] is None or isinstance(document["predecessor"], dict), "binding_invalid",
           field="predecessor")
    return dict(document)


# ---- projection ---------------------------------------------------------------------------------
def next_action(row: dict) -> str:
    state, route = row.get("state"), row.get("route")
    if state == DISPATCHED and isinstance(row.get("hold"), dict):
        return ("conductor cleanup unproven: its execution unit stays held; "
                + str(row["hold"].get("next_owner") or "execution_recovery")
                + " proves parent and tree cleanup or records recovery; no rerun, no replacement")
    if state in OPEN_STATES and isinstance(row.get("hold"), dict):
        return ("no new effect under a changed authorization; " + str(row["hold"].get("next_owner") or "operator")
                + " restores the authorized binding or supersedes this intent")
    if state == INTENDED:
        return "perform the " + str(route) + " effect under this intent"
    if state == PUBLISHED:
        return "admit the successor through the existing Fleet"
    if state == ADMITTED:
        return "wait for the successor operation's terminal outcome"
    if state == DISPATCHED:
        return ("poll the guardian's local evidence; settle the unit and decision only on its cleanup proof; "
                "never relaunch an entered one")
    if state == RETURNED:
        return "route the returned outcome"
    if state == AWAITING_OWNER:
        return {CONDUCTOR: "conductor decision row not yet claimable; retry the guarded dispatch when pending",
                DELIVERY: "owner registers a host delivery plan for the queued release on the policy target",
                NEXT_ITEM: "approved backlog selects the next item"}.get(route, "owner action required")
    if state == RESEARCH_REQUIRED:
        return ("owner submits a scoped research receipt (zeus continuation research-accept) for this exact "
                "intent and attempt set; a coarse disposition alone never releases the hold")
    if state == RECOVERY_REQUIRED:
        return "reconcile through ExecutionRecovery; no fresh invocation on uncertainty"
    if state == PAUSED:
        return "family held after release rejection or rollback; acceptance authority preserved"
    if state == REFUSED:
        return "named owner resolves the refusal; the continuation never widens its own permission"
    return "none"


def view(row: dict) -> dict:
    """Bounded read-only projection: identities, digests, fixed codes and links only."""
    return {"id": row["id"], "family": row["family"], "route": row["route"], "state": row["state"],
            "reason_code": row.get("reason_code"), "origin_job": row["origin_job"], "lane": row.get("lane"),
            "successor_job": row.get("successor_job"), "predecessor_intent": row.get("predecessor_intent"),
            "evidence_sha256": row["evidence_sha256"], "evidence_refs": list(row.get("evidence_refs") or [])[:16],
            "session_mode": row.get("session_mode"), "next_owner": row.get("next_owner"),
            "hold": ({k: row["hold"].get(k) for k in ("reason_code", "next_owner", "field")}
                     if isinstance(row.get("hold"), dict) else None),
            "launch": ({k: row["launch"].get(k) for k in ("id", "sequence", "state", "exit_code")}
                       if isinstance(row.get("launch"), dict) else None),
            "delivery_binding": (delivery_tuple(row["delivery_binding"])
                                 if isinstance(row.get("delivery_binding"), dict) else None),
            "research_receipt": row.get("research_receipt"),
            "next_action": next_action(row), "completion": ROUTE_COMPLETION.get(row["route"]),
            "version": row.get("version"), "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
