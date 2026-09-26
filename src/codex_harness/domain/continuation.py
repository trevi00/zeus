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
# The owner-authorized re-derivation of an accepted change on a NEWER main after its delivery was
# withdrawn as stale (`Continuation.requalify_delivery`). It admits a fresh Fleet operation like a
# successor route, but it is deliberately NOT a successor route: it answers no failure, so it never
# counts against `max_corrections`, the two-strike research trigger or a capacity grant.
REQUALIFICATION = "requalification"
ROUTES = (EVIDENCE_REPAIR, CORRECTION, RESEARCH, RECOVERY, CONDUCTOR, DELIVERY, NEXT_ITEM, REQUALIFICATION)
SUCCESSOR_ROUTES = frozenset({EVIDENCE_REPAIR, CORRECTION})
FAILURE_ROUTES = SUCCESSOR_ROUTES
# Routes whose intent admits a new Fleet operation with its own lane binding (publish -> admit).
ADMITTING_ROUTES = SUCCESSOR_ROUTES | {REQUALIFICATION}
ROUTE_OWNERS = {EVIDENCE_REPAIR: "fleet", CORRECTION: "fleet", RESEARCH: "portfolio_research",
                RECOVERY: "execution_recovery", CONDUCTOR: "conductor", DELIVERY: "host_delivery",
                NEXT_ITEM: "fleet_backlog", REQUALIFICATION: "fleet"}
ROUTE_COMPLETION = {EVIDENCE_REPAIR: "new bound inspection and independent review of the successor",
                    CORRECTION: "pinned successor with retained rejection and session lineage",
                    RESEARCH: "owner scoped research receipt covering the exact family attempts, an accepted "
                              "research dispatch and immutable evidence before another correction",
                    RECOVERY: "bound reconciliation proof; no fresh invocation",
                    CONDUCTOR: "succeeded conductor decision and its Releases record",
                    DELIVERY: "active consumption receipt or verified predecessor rollback",
                    NEXT_ITEM: "next approved backlog item admitted by its owner",
                    REQUALIFICATION: "fresh candidate on the named main, its own independent review, conductor "
                                     "and a new delivery; the withdrawn candidate is never rebased"}

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
# A delivery intent the owner replaced by a requalification intent (`superseded_by`). Terminal; its
# snapshot and history stay, and it is entered only by that explicit owner transition.
SUPERSEDED = "superseded"
STATES = (INTENDED, PUBLISHED, ADMITTED, DISPATCHED, RETURNED, AWAITING_OWNER, RESEARCH_REQUIRED,
          RECOVERY_REQUIRED, PAUSED, REFUSED, COMPLETED, SUPERSEDED)
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
    SUPERSEDED: frozenset(),
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
    **{(route, state): action for route in (EVIDENCE_REPAIR, CORRECTION, REQUALIFICATION)
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
                DELIVERY: (AWAITING_OWNER, COMPLETED, PAUSED, REFUSED, SUPERSEDED),
                RESEARCH: (RESEARCH_REQUIRED, COMPLETED),
                RECOVERY: (RECOVERY_REQUIRED,),
                NEXT_ITEM: (AWAITING_OWNER,),
                REQUALIFICATION: (INTENDED, PUBLISHED, ADMITTED, RETURNED, COMPLETED, REFUSED)}

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
                           investigation, dispatch, run_result, supplement=None, lineage=None, bindings=None,
                           acceptance=None) -> str:
    """Every binding of one owner receipt against authoritative reads; the first gap refuses by name.

    `intent` is the stored research intent, `attempts` its current `research_attempts`, `policy` the
    registered policy row, `jobs` the Fleet rows of the attempts, `observed` job -> `observed_attempt`
    from the lane (absent: unread), `investigation` the Portfolio row, `dispatch` the research
    dispatch row keyed by that investigation and `run_result` the existing `council_result` over its
    bound run row. Unknown, unavailable, partial, foreign or stale evidence never approves.

    Returns how the attempt set is covered: `original_capture` when the dispatch's own job sample
    names every member (the default gate, unchanged), else `owner_supplement` - ONLY when the stored
    typed scope supplement for this intent (`supplement`, with the `lineage`, `bindings` and
    `acceptance` reads it is checked against) passes `check_scope_supplement` again now and names
    exactly this receipt's binding. Evidence refs never imply coverage."""
    members = _check_research(receipt, intent=intent, attempts=attempts, policy=policy, jobs=jobs, observed=observed,
                              investigation=investigation, dispatch=dispatch, run_result=run_result)
    # The dispatch snapshot names at most its job sample; a member outside it is unverifiable here.
    if set(members) <= set(dispatch.get("job_ids") or []):
        return COVERAGE_ORIGINAL
    refuse(isinstance(supplement, dict), "research_scope_unverified", ROUTE_OWNERS[RESEARCH], "dispatch")
    refuse(all(supplement.get(key) == receipt[key] for key in ("intent_id", "policy_id", "policy_sha256", "family",
                                                               "attempts", "investigation"))
           and {k: (supplement.get("dispatch") or {}).get(k) for k in RECEIPT_DISPATCH_FIELDS} == receipt["dispatch"],
           "research_supplement_mismatch", ROUTE_OWNERS[RESEARCH], "dispatch")
    check_scope_supplement(supplement, intent=intent, attempts=attempts, policy=policy, jobs=jobs, observed=observed,
                           investigation=investigation, dispatch=dispatch, run_result=run_result, lineage=lineage,
                           bindings=bindings, acceptance=acceptance)
    return COVERAGE_SUPPLEMENT


def _check_research(receipt: dict, *, intent, attempts: list, policy, jobs: dict, observed: dict, investigation,
                    dispatch, run_result) -> list:
    """The bindings a receipt and a scope supplement share (everything but the job-sample scope);
    returns the member jobs."""
    research = ROUTE_OWNERS[RESEARCH]
    members = _check_held(receipt, intent=intent, attempts=attempts, policy=policy, jobs=jobs, observed=observed)
    refuse(isinstance(investigation, dict), "research_investigation_unknown", research, "investigation")
    refuse(investigation.get("id") == receipt["investigation"] and investigation.get("kind", "failure_family")
           == "failure_family", "research_investigation_mismatch", research, "investigation")
    refuse(set(members) <= set(investigation.get("job_ids") or [])
           and all(jobs[job].get("status") == investigation.get("family_status")
                   and jobs[job].get("reason_code") == investigation.get("reason_code") for job in members),
           "research_investigation_membership", research, "investigation")
    _check_dispatch(receipt, dispatch, run_result)
    return members


def _check_held(receipt: dict, *, intent, attempts: list, policy, jobs: dict, observed: dict) -> list:
    """The held intent and its COMPLETE current attempt set, each attempt's lane evidence read now;
    returns the member jobs."""
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
    return [a["job"] for a in receipt["attempts"]]


def _check_dispatch(receipt: dict, dispatch, run_result) -> None:
    """The current research dispatch of the receipt's investigation: same binding, resolved, accepted."""
    research = ROUTE_OWNERS[RESEARCH]
    refuse(isinstance(dispatch, dict), "research_dispatch_unknown", research, "dispatch")
    bound = receipt["dispatch"]
    refuse(dispatch.get("investigation") == receipt["investigation"] and dispatch.get("kind", "failure_family")
           == "failure_family" and all(dispatch.get(key) == bound[key] for key in RECEIPT_DISPATCH_FIELDS),
           "research_dispatch_mismatch", research, "dispatch")
    refuse(dispatch.get("state") == "resolved", "research_unfinished", research, "dispatch")
    refuse(dispatch.get("result") == RESEARCH_ACCEPTED and (run_result or {}).get("result") == RESEARCH_ACCEPTED,
           "research_not_accepted", research, "dispatch")


def receipt_view(row: dict) -> dict:
    """Bounded projection of one stored receipt: what it covers, never who typed what. `coverage`
    distinguishes the original dispatch capture from the owner scope supplement (a legacy row could
    only have been stored under the original capture)."""
    receipt = row.get("receipt") or {}
    shown = {"intent_id": row.get("id"), "policy_id": receipt.get("policy_id"), "family": receipt.get("family"),
             "covered_jobs": [a.get("job") for a in receipt.get("attempts") or []],
             "inspections": [a.get("inspection") for a in receipt.get("attempts") or []],
             "investigation": receipt.get("investigation"), "dispatch": receipt.get("dispatch"),
             "evidence_refs": list(receipt.get("evidence_refs") or []), "receipt_sha256": row.get("receipt_sha256"),
             "coverage": row.get("coverage") or COVERAGE_ORIGINAL, "supplement_sha256": row.get("supplement_sha256"),
             "accepted_at": row.get("accepted_at"), "authority": RECEIPT_AUTHORITY}
    if receipt.get("schema") != MIXED_RECEIPT_SCHEMA:
        return shown
    # A mixed-family receipt also shows each member's own cause and the lineage and report it is bound to.
    return {**shown, "schema": MIXED_RECEIPT_SCHEMA,
            "causes": [{k: a.get(k) for k in ("job", "investigation", "status", "reason_code")}
                       for a in receipt.get("attempts") or []],
            "captured": list(receipt.get("captured") or []), "lineage": [dict(e) for e in receipt.get("lineage") or []],
            "acceptance": receipt.get("acceptance"), "attestation_ref": receipt.get("attestation_ref"),
            "mixed_authority": MIXED_AUTHORITY}


# ---- owner research scope supplement (SPEC "Research coverage ownership: accepted003 receipt refusal") --
# An accepted CURRENT research dispatch whose immutable job sample omitted a proven continuation
# successor of a captured member. The owner appends ONE typed supplement per research intent: it never
# rewrites the dispatch, its snapshot or any failure verdict. It records current lineage membership
# (every missing member an exact persisted successor intent of a captured member, same policy, family,
# lane and Portfolio target, a terminal known failure) and, SEPARATELY, the owner's explicit semantic
# judgment that the accepted report covers those members (`attestation_ref`): owner judgment, not a
# model verdict and not an algorithmic proof. It is checked at registration AND at every receipt use.
SUPPLEMENT_SCHEMA = "urn:zeus:continuation-research-scope-supplement:1"
SUPPLEMENT_FIELDS = {"schema", "intent_id", "policy_id", "policy_sha256", "family", "attempts", "investigation",
                     "dispatch", "captured", "descendants", "acceptance", "report_ref", "attestation_ref"}
SUPPLEMENT_DISPATCH_FIELDS = RECEIPT_DISPATCH_FIELDS | {"id", "job_ids_sha256"}
SUPPLEMENT_DESCENDANT_FIELDS = {"job", "parent_job", "intent_id"}
SUPPLEMENT_ACCEPTANCE_FIELDS = {"graph_sha256", "candidate_revision", "decision_id"}
SUPPLEMENT_AUTHORITY = ("owner scope supplement: current continuation lineage membership plus the owner's explicit "
                        "semantic coverage judgment; not the original capture, a model verdict, an algorithmic "
                        "proof, a receipt or a repair verdict")
COVERAGE_ORIGINAL, COVERAGE_SUPPLEMENT = "original_capture", "owner_supplement"
LINEAGE_ADMITTED = frozenset({ADMITTED, RETURNED, COMPLETED})
KNOWN_FAILURES = frozenset({"failed", "rejected"})


def _supplement(condition, field: str) -> None:
    refuse(condition, "research_supplement_invalid", "operator", field)


def validate_scope_supplement(document) -> dict:
    """Strict owner supplement; returns the canonical copy. Its receipt-shaped part (intent, policy,
    family, complete attempts, investigation, dispatch binding) is validated by the receipt rules."""
    _supplement(isinstance(document, dict) and set(document) == SUPPLEMENT_FIELDS, "root")
    _supplement(document["schema"] == SUPPLEMENT_SCHEMA, "schema")
    dispatch = document["dispatch"]
    _supplement(isinstance(dispatch, dict) and set(dispatch) == SUPPLEMENT_DISPATCH_FIELDS, "dispatch")
    _supplement(type(dispatch["id"]) is str and INVESTIGATION_REF.fullmatch(dispatch["id"]) is not None, "dispatch.id")
    _supplement(type(dispatch["job_ids_sha256"]) is str and SHA256.fullmatch(dispatch["job_ids_sha256"]) is not None,
                "dispatch.job_ids_sha256")
    refs = [document["report_ref"], document["attestation_ref"]]
    _supplement(all(type(ref) is str and EVIDENCE_REF.fullmatch(ref) for ref in refs) and refs[0] != refs[1],
                "report_ref/attestation_ref")
    try:
        shared = validate_research_receipt({
            "schema": RESEARCH_RECEIPT_SCHEMA, "evidence_refs": refs,
            "dispatch": {k: dispatch[k] for k in RECEIPT_DISPATCH_FIELDS},
            **{k: document[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "attempts",
                                        "investigation")}})
    except ContinuationRefused as exc:
        raise ContinuationRefused("research_supplement_invalid", "operator", exc.field) from None
    captured = document["captured"]
    _supplement(isinstance(captured, list) and 0 < len(captured) <= MAX_RECEIPT_ATTEMPTS
                and len(set(captured)) == len(captured)
                and all(type(job) is str and TOKEN.fullmatch(job) for job in captured), "captured")
    descendants = document["descendants"]
    _supplement(isinstance(descendants, list) and 0 < len(descendants) <= MAX_RECEIPT_ATTEMPTS, "descendants")
    for row in descendants:
        _supplement(isinstance(row, dict) and set(row) == SUPPLEMENT_DESCENDANT_FIELDS, "descendants[]")
        _supplement(all(type(row[k]) is str and TOKEN.fullmatch(row[k]) for k in ("job", "parent_job"))
                    and row["job"] != row["parent_job"], "descendants[].job")
        _supplement(type(row["intent_id"]) is str and SHA256.fullmatch(row["intent_id"]) is not None,
                    "descendants[].intent_id")
    _supplement(len({row["job"] for row in descendants}) == len(descendants), "descendants[].job")
    acceptance = document["acceptance"]
    _supplement(isinstance(acceptance, dict) and set(acceptance) == SUPPLEMENT_ACCEPTANCE_FIELDS, "acceptance")
    _supplement(type(acceptance["graph_sha256"]) is str and SHA256.fullmatch(acceptance["graph_sha256"]) is not None,
                "acceptance.graph_sha256")
    _supplement(type(acceptance["candidate_revision"]) is str and REVISION.fullmatch(acceptance["candidate_revision"])
                is not None, "acceptance.candidate_revision")
    _supplement(type(acceptance["decision_id"]) is str and TOKEN.fullmatch(acceptance["decision_id"]) is not None,
                "acceptance.decision_id")
    return {"schema": SUPPLEMENT_SCHEMA, **{k: shared[k] for k in ("intent_id", "policy_id", "policy_sha256", "family",
                                                                   "attempts", "investigation")},
            "dispatch": {k: dispatch[k] for k in sorted(SUPPLEMENT_DISPATCH_FIELDS)}, "captured": sorted(captured),
            "descendants": sorted(({k: row[k] for k in sorted(SUPPLEMENT_DESCENDANT_FIELDS)} for row in descendants),
                                  key=lambda row: row["job"]),
            "acceptance": {k: acceptance[k] for k in sorted(SUPPLEMENT_ACCEPTANCE_FIELDS)},
            "report_ref": document["report_ref"], "attestation_ref": document["attestation_ref"]}


def accepted_candidate(binding: dict, run_id, acceptance) -> bool:
    """The accepted council's own promotion evidence, read mechanically from authoritative rows: the
    run row and the promotion receipt carry the same graph digest, the receipt names the decision,
    the implementation task succeeded with that candidate revision, and that decision is the
    succeeded accepting `review_lead` of the same revision."""
    acceptance = acceptance if isinstance(acceptance, dict) else {}
    run, promotion = acceptance.get("run"), acceptance.get("promotion")
    task, decision = acceptance.get("task"), acceptance.get("decision")
    if not (isinstance(run, dict) and isinstance(run.get("promotion"), dict) and isinstance(promotion, dict)
            and isinstance(task, dict) and isinstance(decision, dict)):
        return False
    candidate = ((task.get("result") or {}).get("candidate") or {}) if isinstance(task.get("result"), dict) else {}
    reviewed = ((decision.get("input") or {}).get("candidate") or {}) if isinstance(decision.get("input"), dict) else {}
    verdict = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    return (run.get("id") == run_id and run["promotion"].get("graph_sha256") == binding["graph_sha256"]
            and promotion.get("id") == run_id and promotion.get("graph_sha256") == binding["graph_sha256"]
            and (promotion.get("evidence") or {}).get("decision_id") == binding["decision_id"]
            and (promotion.get("evidence") or {}).get("implementation_task_id") == task.get("id")
            and task.get("status") == "succeeded" and candidate.get("revision") == binding["candidate_revision"]
            and decision.get("id") == binding["decision_id"] and decision.get("status") == "succeeded"
            and decision.get("phase") == "review_lead" and verdict.get("accepted") is True
            and reviewed.get("revision") == binding["candidate_revision"])


def check_scope_supplement(supplement: dict, *, intent, attempts: list, policy, jobs: dict, observed: dict,
                           investigation, dispatch, run_result, lineage, bindings, acceptance) -> None:
    """Every binding of one owner scope supplement against authoritative reads (the receipt's own
    checks first); the first gap refuses by name. `lineage` is intent id -> the stored intent row of
    this policy, `bindings` job -> its `portfolio_bindings` row, `acceptance` the accepted run's
    {run, promotion, task, decision} rows. Only exact proven descendants are admitted: an arbitrary
    same-reason job, a foreign family, a broken lineage or a changed current dispatch refuses."""
    research = ROUTE_OWNERS[RESEARCH]
    members = _check_research(supplement, intent=intent, attempts=attempts, policy=policy, jobs=jobs,
                              observed=observed, investigation=investigation, dispatch=dispatch, run_result=run_result)
    bound = supplement["dispatch"]
    refuse(dispatch.get("id", dispatch.get("investigation")) == bound["id"]
           and dispatch.get("job_ids_sha256") == bound["job_ids_sha256"], "research_dispatch_mismatch", research,
           "dispatch")
    sample = set(dispatch.get("job_ids") or [])
    captured = sorted(set(members) & sample)
    refuse(captured and supplement["captured"] == captured, "research_supplement_capture_mismatch", research,
           "captured")
    missing = set(members) - sample
    refuse(missing and {row["job"] for row in supplement["descendants"]} == missing,
           "research_supplement_scope_mismatch", research, "descendants")
    lineage = lineage if isinstance(lineage, dict) else {}
    bindings = bindings if isinstance(bindings, dict) else {}
    # A descendant's parent is a captured member or an already proven descendant (a chain of
    # successors); resolved in lineage order, so a cycle or an orphan never resolves.
    proven, pending = set(captured), list(supplement["descendants"])
    while pending:
        ready = [row for row in pending if row["parent_job"] in proven]
        refuse(ready, "research_supplement_lineage_broken", research, "descendants[].parent_job")
        for row in ready:
            _check_descendant(row, intent, lineage.get(row["intent_id"]), jobs, bindings)
            proven.add(row["job"])
            pending.remove(row)
    refuse(accepted_candidate(supplement["acceptance"], bound["run_id"], acceptance),
           "research_supplement_acceptance_unproven", research, "acceptance")


def _check_descendant(row: dict, intent: dict, successor: dict | None, jobs: dict, bindings: dict,
                      prefix: str = "research_supplement") -> None:
    """One persisted parent -> successor edge of the held family: the exact admitted successor
    intent (same policy, digest, family and lane), both jobs terminal known failures on that lane and
    bound to the same Portfolio target. `prefix` names the gate that asked."""
    research = ROUTE_OWNERS[RESEARCH]
    job, parent = jobs.get(row["job"]), jobs.get(row["parent_job"])
    refuse(isinstance(successor, dict) and successor.get("id") == row["intent_id"]
           and successor.get("policy_id") == intent.get("policy_id")
           and successor.get("policy_sha256") == intent.get("policy_sha256")
           and successor.get("family") == intent.get("family") and successor.get("lane") == intent.get("lane")
           and successor.get("route") in SUCCESSOR_ROUTES and successor.get("state") in LINEAGE_ADMITTED
           and successor.get("origin_job") == row["parent_job"] and successor.get("successor_job") == row["job"]
           and successor_id(row["intent_id"]) == row["job"]
           and ((successor.get("binding") or {}).get("predecessor") or {}).get("job_id") == row["parent_job"],
           prefix + "_lineage_broken", research, "descendants[].intent_id")
    refuse(isinstance(job, dict) and isinstance(parent, dict) and job.get("lane") == parent.get("lane")
           == intent.get("lane") and job.get("status") in KNOWN_FAILURES and parent.get("status") in KNOWN_FAILURES,
           prefix + "_lineage_broken", research, "descendants[].job")
    child, origin = bindings.get(row["job"]), bindings.get(row["parent_job"])
    refuse(isinstance(child, dict) and isinstance(origin, dict)
           and (child.get("project_id"), child.get("criterion_id")) == (origin.get("project_id"),
                                                                        origin.get("criterion_id")),
           prefix + "_ownership_mismatch", research, "descendants[].job")


def supplement_view(row: dict) -> dict:
    """Bounded projection of one stored supplement, kept apart from the original capture."""
    supplement = row.get("supplement") or {}
    return {"intent_id": row.get("id"), "coverage": COVERAGE_SUPPLEMENT,
            "captured": list(supplement.get("captured") or []),
            "descendants": [dict(d) for d in supplement.get("descendants") or []],
            "dispatch": supplement.get("dispatch"), "acceptance": supplement.get("acceptance"),
            "report_ref": supplement.get("report_ref"), "attestation_ref": supplement.get("attestation_ref"),
            "supplement_sha256": row.get("supplement_sha256"), "recorded_at": row.get("recorded_at"),
            "authority": SUPPLEMENT_AUTHORITY}


# ---- mixed-cause family receipt (SPEC "Mixed-cause continuation research receipt") ---------------------
# `research_attempts` groups successive failures of ONE policy family, while a Portfolio investigation
# groups jobs by ONE (status, reason code); a family whose members failed for different reasons (a
# rejected parent and its evidence-refused successor) is held by one intent but lies in several
# investigations, so the schema-1 membership gate truthfully refuses it. This versioned receipt,
# submitted through the same `research-accept`, covers such a set without asserting a shared cause:
# every member names its OWN authoritative investigation, status and reason code; at least one member
# is captured by the current accepted research dispatch of `investigation`; every other member is
# connected to a captured one through persisted continuation parent -> successor intents (an ancestor
# or a descendant, never a name, prefix or similarity) inside the same policy, family, lane and Portfolio
# target; the accepted report is bound through its promotion evidence (`accepted_candidate`); and the
# owner's immutable attestation states that this exact report covers this exact set. Schema 1 and the
# scope supplement are unchanged. It grants no acceptance, correction budget, deployment or release.
MIXED_RECEIPT_SCHEMA = "urn:zeus:continuation-research-receipt:2"
MIXED_FIELDS = {"schema", "intent_id", "policy_id", "policy_sha256", "family", "attempts", "lineage", "investigation",
                "dispatch", "captured", "acceptance", "evidence_refs", "attestation_ref"}
MIXED_ATTEMPT_FIELDS = RECEIPT_ATTEMPT_FIELDS | {"investigation", "status", "reason_code"}
MIXED_AUTHORITY = ("owner mixed-cause family coverage: each member's own authoritative failure cause, persisted "
                   "continuation lineage and the owner's attestation that one accepted report covers the exact "
                   "set; no shared cause is asserted, and it is not an acceptance, a repair verdict or a budget")
COVERAGE_MIXED = "mixed_family"


def validate_mixed_receipt(document) -> dict:
    """Strict owner mixed-cause receipt; returns the canonical copy. Its schema-1 part (intent,
    policy, family, attempts, investigation, dispatch binding, evidence refs) is validated by the
    schema-1 rules; members must lie in at least two distinct investigations."""
    _receipt(isinstance(document, dict) and set(document) == MIXED_FIELDS, "root")
    _receipt(document["schema"] == MIXED_RECEIPT_SCHEMA, "schema")
    attempts, dispatch = document["attempts"], document["dispatch"]
    _receipt(isinstance(attempts, list) and all(isinstance(a, dict) and set(a) == MIXED_ATTEMPT_FIELDS for a in attempts),
             "attempts[]")
    _receipt(isinstance(dispatch, dict) and set(dispatch) == SUPPLEMENT_DISPATCH_FIELDS, "dispatch")
    shared = validate_research_receipt({
        "schema": RESEARCH_RECEIPT_SCHEMA, "dispatch": {k: dispatch[k] for k in RECEIPT_DISPATCH_FIELDS},
        "attempts": [{k: a[k] for k in RECEIPT_ATTEMPT_FIELDS} for a in attempts],
        **{k: document[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "investigation",
                                    "evidence_refs")}})
    for attempt in attempts:
        _receipt(type(attempt["investigation"]) is str and INVESTIGATION_REF.fullmatch(attempt["investigation"]),
                 "attempts[].investigation")
        _receipt(attempt["status"] in KNOWN_FAILURES, "attempts[].status")
        _receipt(type(attempt["reason_code"]) is str and TOKEN.fullmatch(attempt["reason_code"]) is not None,
                 "attempts[].reason_code")
    _receipt(len({a["investigation"] for a in attempts}) > 1, "attempts[].investigation")
    _receipt(type(dispatch["id"]) is str and INVESTIGATION_REF.fullmatch(dispatch["id"]) is not None, "dispatch.id")
    _receipt(type(dispatch["job_ids_sha256"]) is str and SHA256.fullmatch(dispatch["job_ids_sha256"]) is not None,
             "dispatch.job_ids_sha256")
    members = {a["job"] for a in attempts}
    captured = document["captured"]
    _receipt(isinstance(captured, list) and 0 < len(captured) < len(members) and len(set(captured)) == len(captured)
             and set(captured) <= members, "captured")
    lineage = document["lineage"]
    _receipt(isinstance(lineage, list) and len(lineage) == len(members) - 1, "lineage")
    for edge in lineage:
        _receipt(isinstance(edge, dict) and set(edge) == SUPPLEMENT_DESCENDANT_FIELDS, "lineage[]")
        _receipt(all(type(edge[k]) is str and edge[k] in members for k in ("job", "parent_job"))
                 and edge["job"] != edge["parent_job"], "lineage[].job")
        _receipt(type(edge["intent_id"]) is str and SHA256.fullmatch(edge["intent_id"]) is not None,
                 "lineage[].intent_id")
    _receipt(len({(e["parent_job"], e["job"]) for e in lineage}) == len(lineage), "lineage[].job")
    acceptance = document["acceptance"]
    _receipt(isinstance(acceptance, dict) and set(acceptance) == SUPPLEMENT_ACCEPTANCE_FIELDS
             and type(acceptance["graph_sha256"]) is str and SHA256.fullmatch(acceptance["graph_sha256"]) is not None
             and type(acceptance["candidate_revision"]) is str
             and REVISION.fullmatch(acceptance["candidate_revision"]) is not None
             and type(acceptance["decision_id"]) is str and TOKEN.fullmatch(acceptance["decision_id"]) is not None,
             "acceptance")
    attestation = document["attestation_ref"]
    _receipt(type(attestation) is str and EVIDENCE_REF.fullmatch(attestation) is not None
             and attestation not in shared["evidence_refs"], "attestation_ref")
    causes = {a["job"]: {k: a[k] for k in ("investigation", "status", "reason_code")} for a in attempts}
    return {**shared, "schema": MIXED_RECEIPT_SCHEMA,
            "attempts": [{**a, **causes[a["job"]]} for a in shared["attempts"]],
            "dispatch": {k: dispatch[k] for k in sorted(SUPPLEMENT_DISPATCH_FIELDS)}, "captured": sorted(captured),
            "lineage": sorted(({k: e[k] for k in sorted(SUPPLEMENT_DESCENDANT_FIELDS)} for e in lineage),
                              key=lambda e: (e["parent_job"], e["job"])),
            "acceptance": {k: acceptance[k] for k in sorted(SUPPLEMENT_ACCEPTANCE_FIELDS)},
            "attestation_ref": attestation}


def validate_receipt(document) -> dict:
    """The owner's receipt under its declared version: schema 2 is the mixed-cause family receipt,
    anything else is held to the unchanged schema-1 rules."""
    if isinstance(document, dict) and document.get("schema") == MIXED_RECEIPT_SCHEMA:
        return validate_mixed_receipt(document)
    return validate_research_receipt(document)


def receipt_refs(receipt: dict) -> list:
    """Every content-addressed ref whose actual bytes a receipt depends on."""
    refs = list(receipt["evidence_refs"])
    return refs + [receipt["attestation_ref"]] if receipt.get("schema") == MIXED_RECEIPT_SCHEMA else refs


def check_mixed_receipt(receipt: dict, *, intent, attempts: list, policy, jobs: dict, observed: dict, investigations,
                        dispatch, run_result, lineage, bindings, acceptance) -> str:
    """Every binding of one mixed-cause receipt against authoritative reads; the first gap refuses by
    name. `investigations` is investigation id -> the Portfolio row for every member's named one,
    `dispatch` the CURRENT dispatch of `receipt.investigation` with `run_result` over its run row,
    `lineage` intent id -> stored intent row of this policy, `bindings` job -> Portfolio binding and
    `acceptance` the accepted run's {run, promotion, task, decision}. Returns `mixed_family`."""
    research = ROUTE_OWNERS[RESEARCH]
    members = _check_held(receipt, intent=intent, attempts=attempts, policy=policy, jobs=jobs, observed=observed)
    investigations = investigations if isinstance(investigations, dict) else {}
    # Each member's OWN cause: the authoritative Portfolio investigation holding it under exactly the
    # status and reason code its Fleet row carries. Different causes are allowed; none is merged.
    for attempt in receipt["attempts"]:
        row, job = investigations.get(attempt["investigation"]), jobs[attempt["job"]]
        refuse(isinstance(row, dict), "research_investigation_unknown", research, "attempts[].investigation")
        refuse(row.get("id") == attempt["investigation"] and row.get("kind", "failure_family") == "failure_family",
               "research_investigation_mismatch", research, "attempts[].investigation")
        refuse(attempt["job"] in (row.get("job_ids") or [])
               and job.get("status") == row.get("family_status") == attempt["status"]
               and job.get("reason_code") == row.get("reason_code") == attempt["reason_code"],
               "research_investigation_membership", research, "attempts[].investigation")
    _check_dispatch(receipt, dispatch, run_result)
    bound = receipt["dispatch"]
    refuse(dispatch.get("id", dispatch.get("investigation")) == bound["id"]
           and dispatch.get("job_ids_sha256") == bound["job_ids_sha256"], "research_dispatch_mismatch", research,
           "dispatch")
    # The dispatch's own immutable sample names the captured members, and only members of its investigation.
    causes = {a["job"]: a["investigation"] for a in receipt["attempts"]}
    captured = sorted(set(members) & set(dispatch.get("job_ids") or []))
    refuse(captured and receipt["captured"] == captured
           and all(causes[job] == receipt["investigation"] for job in captured),
           "research_mixed_capture_mismatch", research, "captured")
    # Every other member through persisted parent -> successor edges, walked from the captured ones in
    # either direction; a cycle, an orphan or an edge to a non-member never resolves.
    lineage = lineage if isinstance(lineage, dict) else {}
    bindings = bindings if isinstance(bindings, dict) else {}
    proven, pending = set(captured), list(receipt["lineage"])
    while pending:
        ready = [e for e in pending if (e["parent_job"] in proven) != (e["job"] in proven)]
        refuse(ready, "research_mixed_lineage_broken", research, "lineage")
        for edge in ready:
            _check_descendant(edge, intent, lineage.get(edge["intent_id"]), jobs, bindings, prefix="research_mixed")
            proven.update((edge["job"], edge["parent_job"]))
            pending.remove(edge)
    refuse(proven == set(members), "research_mixed_lineage_broken", research, "lineage")
    refuse(accepted_candidate(receipt["acceptance"], bound["run_id"], acceptance),
           "research_mixed_acceptance_unproven", research, "acceptance")
    return COVERAGE_MIXED


# ---- exact evidence-repair capacity grant (SPEC "Exact evidence-repair capacity authorization") --------
# `max_corrections` stays immutable and every successor keeps counting. The ONLY way past an exhausted
# budget is the owner's typed one-use grant for ONE exact `evidence_repair` intent refused at creation
# with `correction_budget_exhausted`: it pins the policy, family, source attempt and inspection, the
# retained candidate, the family's latest completed research receipt and an immutable owner rationale.
# Recorded together with the move of THAT intent from `refused` to `intended` (its successor id is the
# one the intent always derived), so it authorizes one successor at most; the original refusal stays
# as a snapshot and in the intent history. It is not an acceptance, a budget-ledger change, a model
# authority, a deployment or an incident closure.
CAPACITY_GRANT_SCHEMA = "urn:zeus:continuation-capacity-grant:1"
CAPACITY_FIELDS = {"schema", "policy_id", "policy_sha256", "family", "intent_id", "route", "refusal", "source",
                   "candidate", "research_receipt_sha256", "rationale_ref"}
CAPACITY_SOURCE_FIELDS = {"job", "generation", "attempt", "evidence_sha256", "inspection"}
CAPACITY_CANDIDATE_FIELDS = {"revision", "tree"}
CAPACITY_REFUSAL = "correction_budget_exhausted"
CAPACITY_AUTHORIZED = "capacity_grant_authorized"
CAPACITY_EXTRA = 1
CAPACITY_AUTHORITY = ("owner one-use evidence-repair capacity for one exact refused intent: not a code "
                      "acceptance, a budget-ledger change, a model authority, a deployment or an incident closure")
# Family rows that are still owed an effect or an owner: an active, unknown or unresolved lineage.
CAPACITY_ACTIVE = OPEN_STATES | {RECOVERY_REQUIRED, PAUSED}


def _grant(condition, field: str) -> None:
    refuse(condition, "capacity_grant_invalid", "operator", field)


def validate_capacity_grant(document) -> dict:
    """Strict owner grant; returns the canonical copy. Only an `evidence_repair` refused for
    `correction_budget_exhausted` is grantable; unknown or missing fields are refused."""
    _grant(isinstance(document, dict) and set(document) == CAPACITY_FIELDS, "root")
    _grant(document["schema"] == CAPACITY_GRANT_SCHEMA, "schema")
    _grant(type(document["policy_id"]) is str and TOKEN.fullmatch(document["policy_id"]) is not None, "policy_id")
    for key in ("policy_sha256", "intent_id", "research_receipt_sha256"):
        _grant(type(document[key]) is str and SHA256.fullmatch(document[key]) is not None, key)
    _grant(type(document["family"]) is str and TOKEN.fullmatch(document["family"]) is not None, "family")
    refuse(document["route"] == EVIDENCE_REPAIR, "capacity_route_unsupported", "operator", "route")
    refuse(document["refusal"] == CAPACITY_REFUSAL, "capacity_refusal_unsupported", "operator", "refusal")
    source = document["source"]
    _grant(isinstance(source, dict) and set(source) == CAPACITY_SOURCE_FIELDS, "source")
    _grant(type(source["job"]) is str and TOKEN.fullmatch(source["job"]) is not None, "source.job")
    _grant(all(type(source[k]) is int and 0 <= source[k] < 10_000 for k in ("generation", "attempt")),
           "source.attempt")
    _grant(type(source["evidence_sha256"]) is str and SHA256.fullmatch(source["evidence_sha256"]) is not None,
           "source.evidence_sha256")
    _grant(type(source["inspection"]) is str and TOKEN.fullmatch(source["inspection"]) is not None,
           "source.inspection")
    candidate = document["candidate"]
    _grant(isinstance(candidate, dict) and set(candidate) == CAPACITY_CANDIDATE_FIELDS
           and all(type(candidate[k]) is str and REVISION.fullmatch(candidate[k]) for k in CAPACITY_CANDIDATE_FIELDS),
           "candidate")
    _grant(type(document["rationale_ref"]) is str and EVIDENCE_REF.fullmatch(document["rationale_ref"]) is not None,
           "rationale_ref")
    return {"schema": CAPACITY_GRANT_SCHEMA, **{k: document[k] for k in (
                "policy_id", "policy_sha256", "family", "intent_id", "route", "refusal", "research_receipt_sha256",
                "rationale_ref")},
            "source": {k: source[k] for k in sorted(CAPACITY_SOURCE_FIELDS)},
            "candidate": {k: candidate[k] for k in sorted(CAPACITY_CANDIDATE_FIELDS)}}


def check_capacity_refusal(grant: dict, intent) -> None:
    """The intent a NEW grant names: this policy's exact `evidence_repair` observation, refused at
    creation for an exhausted budget and never the owner of any effect."""
    refuse(isinstance(intent, dict), "capacity_intent_unknown", "operator", "intent_id")
    refuse(intent.get("policy_id") == grant["policy_id"] and intent.get("policy_sha256") == grant["policy_sha256"],
           "capacity_policy_foreign", "operator", "policy")
    refuse(intent.get("family") == grant["family"], "capacity_family_mismatch", "operator", "family")
    refuse(intent.get("route") == EVIDENCE_REPAIR and intent.get("state") == REFUSED
           and intent.get("reason_code") == CAPACITY_REFUSAL and effect_free(intent)
           and isinstance(intent.get("authorization"), dict), "capacity_refusal_mismatch", "operator", "intent_id")


def check_capacity_source(grant: dict, intent: dict, job, evidence: dict) -> None:
    """The refused observation is still exactly what the lane shows now: the same terminal Fleet row,
    route, decisive evidence, attempt, inspection and retained candidate. Anything else holds."""
    source = grant["source"]
    refuse(intent.get("origin_job") == source["job"] and intent.get("evidence_sha256") == source["evidence_sha256"]
           and (intent.get("generation"), intent.get("attempt")) == (source["generation"], source["attempt"]),
           "capacity_source_mismatch", "operator", "source")
    refuse(isinstance(job, dict) and job.get("id") == source["job"] and job.get("lane") == intent.get("lane")
           and job.get("updated_at") == intent.get("job_updated_at")
           and (intent["authorization"].get("source") or {}).get("manifest_sha256") == job.get("manifest_sha256"),
           "capacity_source_changed", "operator", "source.job")
    routed = classify(job, evidence)
    refuse(routed.get("route") == EVIDENCE_REPAIR and attempt_of(evidence) == {
               "generation": source["generation"], "attempt": source["attempt"]}
           and evidence_digest(job, evidence, EVIDENCE_REPAIR) == source["evidence_sha256"],
           "capacity_source_changed", "operator", "source")
    handoff = (evidence.get("operation") or {}).get("owner_handoff") or {}
    refuse((handoff.get("inspection") or {}).get("id") == source["inspection"], "capacity_inspection_changed",
           "operator", "source.inspection")
    task = evidence.get("task") if isinstance(evidence.get("task"), dict) else {}
    candidate = (task.get("result") or {}).get("candidate") or {}
    refuse({k: candidate.get(k) for k in CAPACITY_CANDIDATE_FIELDS} == grant["candidate"],
           "capacity_candidate_changed", "operator", "candidate")


def check_capacity_family(grant: dict, intent: dict, intents: list, jobs: dict) -> dict:
    """The family around the granted intent, from durable rows: no other active, unknown or
    unresolved row, every family job terminal and known, and the family's LATEST research is completed
    by exactly the pinned receipt before the refusal was observed. Returns that research intent."""
    family = [row for row in intents if row.get("policy_id") == grant["policy_id"]
              and row.get("family") == grant["family"] and row["id"] != intent["id"]]
    refuse(not any(row.get("state") in CAPACITY_ACTIVE for row in family), "capacity_family_active", "operator",
           "family")
    members = {job for row in family + [intent] for job in (row.get("origin_job"), row.get("successor_job")) if job}
    members.discard(intent.get("successor_job"))   # the granted successor itself, once reserved
    refuse(all(isinstance(jobs.get(job), dict) and jobs[job].get("status") in {"accepted", "rejected", "failed",
                                                                                "exhausted"} for job in members),
           "capacity_family_active", "operator", "family")
    research = sorted((row for row in family if row.get("route") == RESEARCH),
                      key=lambda r: (str(r.get("created_at")), r["id"]))
    refuse(research, "capacity_research_unresolved", ROUTE_OWNERS[RESEARCH], "research_receipt_sha256")
    latest = research[-1]
    refuse(latest.get("state") == COMPLETED and latest.get("research_receipt") == grant["research_receipt_sha256"]
           and (str(latest.get("created_at")), latest["id"]) < (str(intent.get("created_at")), intent["id"]),
           "capacity_research_mismatch", ROUTE_OWNERS[RESEARCH], "research_receipt_sha256")
    return latest


def capacity_count(intents: list, policy_id: str, family: str) -> int:
    """The family's successors as `_observe` counts them against `max_corrections`."""
    return sum(1 for row in intents if row.get("policy_id") == policy_id and row.get("family") == family
               and row.get("route") in SUCCESSOR_ROUTES and row.get("state") != REFUSED)


def capacity_view(row: dict, intent) -> dict:
    """Bounded projection of one stored grant: the original cap and count kept apart from the explicit
    extra capacity, the linked refusal, the successor it reserved and what remains of the grant."""
    grant, recorded = row.get("grant") or {}, row.get("capacity") or {}
    intent = intent if isinstance(intent, dict) else {}
    reserved = intent.get("capacity_grant") == row.get("grant_sha256") and intent.get("state") != REFUSED \
        and intent.get("successor_job") == row.get("successor_job")
    return {"intent_id": row.get("id"), "policy_id": grant.get("policy_id"), "family": grant.get("family"),
            "grant_sha256": row.get("grant_sha256"),
            "rationale_ref": grant.get("rationale_ref"), "research_receipt_sha256": grant.get("research_receipt_sha256"),
            "source": grant.get("source"), "candidate": grant.get("candidate"),
            "original_cap": recorded.get("max_corrections"), "original_count": recorded.get("counted"),
            "explicit_capacity": recorded.get("extra"), "successor_job": row.get("successor_job"),
            "consumed": reserved, "remaining": 0 if reserved else recorded.get("extra"),
            "state": intent.get("state"), "refusal": row.get("refusal"), "recorded_at": row.get("recorded_at"),
            "authority": CAPACITY_AUTHORITY}


# ---- owner delivery requalification (SPEC aibox-migration-001 s15) --------------------------------
# One owner document names ONE delivery intent whose HostDelivery plan the owner already withdrew as
# stale, the exact release/candidate/plan it withdrew and the main the change is re-derived on. Recorded
# together with the move of that intent to `superseded` and the creation of one `requalification`
# intent (never a TRANSITIONS edge, like the capacity grant). It is not an acceptance, a rebase of the
# withdrawn candidate, a new goal or a budget change: the successor is a fresh Fleet operation whose
# candidate needs its own review, conductor and delivery.
REQUALIFICATION_SCHEMA = "urn:zeus:continuation-delivery-requalification:1"
REQUALIFICATION_FIELDS = {"schema", "policy_id", "policy_sha256", "intent_id", "family", "release_id", "candidate",
                          "plan", "withdrawal_reason", "main_revision", "rationale_ref"}
# Optional strict block (owner review R1): the goal document of the SAME goal (path and criterion) changed
# between the origin's base and `main_revision`. Absent = the goal bytes at that main must be unchanged.
GOAL_MIGRATION = "goal_migration"
GOAL_MIGRATION_FIELDS = {"path", "criterion", "from_sha256", "to_sha256", "review_ref"}
# What the stored comparison record claims: the owner recorded a review reference, not that this
# controller reviewed the goal diff.
GOAL_MIGRATION_REVIEW = "owner_reference_recorded"
REQUALIFICATION_CANDIDATE_FIELDS = {"revision", "tree", "base"}
REQUALIFICATION_PLAN_FIELDS = {"plan_id", "plan_sha256"}
REQUALIFICATION_REASONS = ("reviewed_base_moved", "descriptor_predecessor_moved", "merged_tree_mismatch")
REQUALIFICATION_AUTHORIZED = "delivery_requalification_authorized"
REQUALIFICATION_REQUALIFIABLE = frozenset({AWAITING_OWNER, PAUSED})
REQUALIFICATION_AUTHORITY = ("owner re-derivation of one withdrawn delivery on a named main: not an acceptance, "
                             "a rebase, a new goal, a budget change, a merge or a deployment")
TREE_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _requalification(condition, field: str) -> None:
    refuse(condition, "requalification_invalid", "operator", field)


def validate_requalification(document) -> dict:
    """Strict owner document; returns the canonical copy. Unknown or missing fields are refused; the
    optional `goal_migration` block is kept only when present (absent keeps the canonical shape)."""
    _requalification(isinstance(document, dict) and set(document) in (
        REQUALIFICATION_FIELDS, REQUALIFICATION_FIELDS | {GOAL_MIGRATION}), "root")
    _requalification(document["schema"] == REQUALIFICATION_SCHEMA, "schema")
    _requalification(type(document["policy_id"]) is str and TOKEN.fullmatch(document["policy_id"]) is not None,
                     "policy_id")
    for key in ("policy_sha256", "intent_id"):
        _requalification(type(document[key]) is str and SHA256.fullmatch(document[key]) is not None, key)
    for key in ("family", "release_id"):
        _requalification(type(document[key]) is str and TOKEN.fullmatch(document[key]) is not None, key)
    candidate = document["candidate"]
    _requalification(isinstance(candidate, dict) and set(candidate) == REQUALIFICATION_CANDIDATE_FIELDS
                     and all(type(candidate[k]) is str and REVISION.fullmatch(candidate[k]) for k in ("revision", "base"))
                     and type(candidate["tree"]) is str and TREE_ID.fullmatch(candidate["tree"]) is not None,
                     "candidate")
    plan = document["plan"]
    _requalification(isinstance(plan, dict) and set(plan) == REQUALIFICATION_PLAN_FIELDS
                     and type(plan["plan_id"]) is str and TOKEN.fullmatch(plan["plan_id"]) is not None
                     and type(plan["plan_sha256"]) is str and SHA256.fullmatch(plan["plan_sha256"]) is not None,
                     "plan")
    refuse(document["withdrawal_reason"] in REQUALIFICATION_REASONS, "requalification_reason_unsupported", "operator",
           "withdrawal_reason")
    _requalification(type(document["main_revision"]) is str and REVISION.fullmatch(document["main_revision"])
                     is not None, "main_revision")
    _requalification(type(document["rationale_ref"]) is str and EVIDENCE_REF.fullmatch(document["rationale_ref"])
                     is not None, "rationale_ref")
    canonical = {"schema": REQUALIFICATION_SCHEMA,
                 **{k: document[k] for k in ("policy_id", "policy_sha256", "intent_id", "family", "release_id",
                                             "withdrawal_reason", "main_revision", "rationale_ref")},
                 "candidate": {k: candidate[k] for k in sorted(REQUALIFICATION_CANDIDATE_FIELDS)},
                 "plan": {k: plan[k] for k in sorted(REQUALIFICATION_PLAN_FIELDS)}}
    if GOAL_MIGRATION in document:
        canonical[GOAL_MIGRATION] = _goal_migration(document[GOAL_MIGRATION], document["rationale_ref"])
    return canonical


def _goal_migration(block, rationale_ref: str) -> dict:
    """The strict block: an actual digest change of one goal document under an owner-recorded review
    reference distinct from the rationale. Whether the digests are the stored and the real blobs is
    decided against authoritative reads, not here."""
    from codex_harness.domain.operation import safe_relative_path

    def valid(condition):
        _requalification(condition, GOAL_MIGRATION)

    valid(isinstance(block, dict) and set(block) == GOAL_MIGRATION_FIELDS)
    valid(type(block["path"]) is str and safe_relative_path(block["path"]) and block["path"].lower().endswith(".md"))
    valid(type(block["criterion"]) is str and 0 < len(block["criterion"].strip()) <= 400)
    valid(all(type(block[k]) is str and SHA256.fullmatch(block[k]) is not None for k in ("from_sha256", "to_sha256")))
    valid(block["from_sha256"] != block["to_sha256"])
    valid(type(block["review_ref"]) is str and EVIDENCE_REF.fullmatch(block["review_ref"]) is not None
          and block["review_ref"] != rationale_ref)
    return {k: block[k] for k in sorted(GOAL_MIGRATION_FIELDS)}


def migrated_goals(policy_id: str, policy_sha256: str, rows) -> list:
    """The goal migrations the owner recorded for THIS policy digest in intact stored requalifications
    (`document_sha256 == digest(document)` and the stored comparison naming the same digests). A tampered
    or foreign row contributes nothing."""
    out = []
    for row in rows or ():
        document = row.get("document") if isinstance(row, dict) else None
        block = document.get(GOAL_MIGRATION) if isinstance(document, dict) else None
        recorded = row.get(GOAL_MIGRATION) if isinstance(row, dict) else None
        if not (isinstance(block, dict) and isinstance(recorded, dict)
                and row.get("document_sha256") == digest(document)
                and document.get("policy_id") == policy_id and document.get("policy_sha256") == policy_sha256
                and (recorded.get("from") or {}).get("sha256") == block.get("from_sha256")
                and (recorded.get("to") or {}).get("sha256") == block.get("to_sha256")):
            continue
        out.append({k: block[k] for k in ("path", "criterion", "from_sha256", "to_sha256")})
    return sorted(out, key=lambda m: (m["path"], m["criterion"], m["from_sha256"], m["to_sha256"]))


def goal_frame(policy: dict, migrations: list) -> dict:
    """The policy as membership reads it: its pinned goals plus every recorded migration target reachable
    from one of them (same path and criterion, from a goal already in the frame). The pinned policy, its
    digest and every other field are unchanged; this is the owner's recorded extension beside the pin, as
    a capacity grant is beside the cap."""
    goals = [dict(goal) for goal in policy["goals"]]
    known = {(g["path"], g["sha256"], g["criterion"]) for g in goals}
    changed = True
    while changed:
        changed = False
        for m in migrations:
            target = (m["path"], m["to_sha256"], m["criterion"])
            if (m["path"], m["from_sha256"], m["criterion"]) in known and target not in known:
                known.add(target)
                goals.append({"path": m["path"], "sha256": m["to_sha256"], "criterion": m["criterion"]})
                changed = True
    if len(goals) == len(policy["goals"]):
        return policy
    return {**policy, "goals": sorted(goals, key=lambda g: (g["path"], g["criterion"], g["sha256"]))}


def requalification_id(intent: str) -> str:
    """The ONE requalification intent a delivery intent can be superseded by: a restart, a replay or a
    second owner command derives the same intent and therefore the same successor id."""
    return digest(["continuation_requalification", intent])


REQUALIFICATION_PREFACE = ("Requalification of an accepted change on a newer main (continuation). Its reviewed "
                           "candidate was withdrawn because its reviewed base no longer holds; re-derive the same "
                           "accepted change on this base. Keep the goal, allowed paths and acceptance criteria "
                           "unchanged; the new candidate needs its own independent review.")


def requalification_manifest(origin: dict, main_revision: str, successor: str, references: dict,
                             goal_sha256: str | None = None) -> dict:
    """The fresh operation: the origin's goal, plan, allowed paths, acceptance criteria, budget and
    Claude controls unchanged, the base moved to `main_revision` and only the id and the objective's
    fixed preface differ. `references` are identities only, never model text. `goal_sha256` is the
    verified owner goal migration's target digest (the same goal path, criterion and rationale at the
    new base); None keeps the origin's digest."""
    refuse(REVISION.fullmatch(str(main_revision or "")) is not None, "requalification_invalid", field="main_revision")
    plan = origin["plan"]
    lines = [REQUALIFICATION_PREFACE, "Continuation references: " + ", ".join(
        f"{key}={references[key]}" for key in sorted(references) if references[key] is not None)]
    goal = dict(origin["goal"])
    if goal_sha256 is not None:
        refuse(SHA256.fullmatch(str(goal_sha256)) is not None, "requalification_invalid", field=GOAL_MIGRATION)
        goal["sha256"] = goal_sha256
    manifest = {"schema": origin["schema"], "id": successor, "base_revision": main_revision,
                "goal": goal,
                "plan": {"objective": "\n".join(lines) + "\n\n" + plan["objective"],
                         "acceptance_criteria": list(plan["acceptance_criteria"]),
                         "allowed_paths": list(plan["allowed_paths"])},
                "budget": dict(origin["budget"]), "claude": dict(origin["claude"])}
    if "design" in origin:
        manifest["design"] = dict(origin["design"])
    return manifest


def requalification_view(row: dict) -> dict:
    """Bounded projection of one stored requalification: identities, codes and links only."""
    document = row.get("document") or {}
    return {"intent_id": row.get("id"), "requalification_intent": row.get("requalification_intent"),
            "successor_job": row.get("successor_job"), "document_sha256": row.get("document_sha256"),
            "release_id": document.get("release_id"), "candidate": document.get("candidate"),
            "plan": document.get("plan"), "withdrawal_reason": document.get("withdrawal_reason"),
            "main_revision": document.get("main_revision"), "rationale_ref": document.get("rationale_ref"),
            "goal_migration": row.get(GOAL_MIGRATION),
            "superseded": row.get("superseded"), "recorded_at": row.get("recorded_at"),
            "authority": REQUALIFICATION_AUTHORITY}


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
    refuse(document["route"] in (None, *sorted(ADMITTING_ROUTES)), "binding_invalid", field="route")
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
    if state == SUPERSEDED:
        return ("superseded by the owner's delivery requalification " + str(row.get("superseded_by"))
                + "; the withdrawn delivery and this intent's history are kept")
    if state == REFUSED:
        if route == EVIDENCE_REPAIR and row.get("reason_code") == CAPACITY_REFUSAL:
            return ("correction budget exhausted; only an explicit owner capacity grant for this exact intent "
                    "(zeus continuation capacity-grant) admits one repair; the budget itself never grows")
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
            "capacity_grant": row.get("capacity_grant"),
            "requalification": row.get("requalification"), "superseded_by": row.get("superseded_by"),
            "refusal": ({k: row["refusal"].get(k) for k in ("state", "reason_code", "next_owner", "version", "updated_at")}
                        if isinstance(row.get("refusal"), dict) else None),
            "next_action": next_action(row), "completion": ROUTE_COMPLETION.get(row["route"]),
            "version": row.get("version"), "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
