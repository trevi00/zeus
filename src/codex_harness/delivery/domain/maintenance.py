"""Active-generation maintenance of an ACTIVE, consumed managed delivery (INV-HOST-DELIVERY-MAINTENANCE-001).

Layer: domain
Context: delivery
Owns: the maintenance document and its identity, the generation lifecycle table, the applicability, readiness and
restart-classification policy and the generation observation validator (pure policy over dictionaries)
Does not own: the maintenance use case (`application/host_delivery/maintenance.py`), the generation recorded in the
intent and its projection (`host_delivery.py`: `maintenance_of`, `maintenance_view`), the host adapters
Entry points: validate_active_generation, generation_id, maintenance_applicable, classify_restart,
new_generation_refusal, fleet_ready_refusal, validate_generation_observation, maintenance_hold
Contracts: INV-HOST-DELIVERY-MAINTENANCE-001

Ported from main b9d8f15 (S2R, reviewed) `domain/host_delivery.py` (the hunks after M7 e38aa722); the bodies are S2R's.
The generation state names, `maintenance_of`, `maintenance_open` and `maintenance_view` stay in `host_delivery.py`
(`delivery_status` projects them and this module imports it); they are re-exported here so this module holds the whole
S2R maintenance surface.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime

from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    ACTOR_ID,
    AWAITING_CONSUMPTION,
    BLOCKED,
    CANARY_FLEET,
    DIGEST_HEX,
    DRAIN_INTENDED,
    EVIDENCE_REF,
    FAILED,
    GENERATION_ARMED,
    GENERATION_BOUND,
    GENERATION_FAILED,
    GENERATION_LAUNCHED,
    GENERATION_REQUESTED,
    GENERATION_STARTED,
    GENERATION_STATES,
    INSTANCE,
    KIND_MANAGED_SYSTEMD,
    MIGRATION_RESERVING,
    NEXT_PHASE,
    OUTCOME_ACTIVE,
    POST_MERGE_OPEN,
    ROLLING_BACK,
    SHA256,
    SWITCHING,
    VERIFYING,
    DeliveryRefused,
    _bounded_int,
    _hex,
    _token,
    consumption_verdict,
    descriptor_digest,
    maintenance_of,
    maintenance_open,
    maintenance_view,
    receipt_identity,
    validate_receipt,
)
from codex_harness.kernel.ids import digest

# ----- active-generation maintenance (INV-HOST-DELIVERY-MAINTENANCE-001) -----------------------------
# An explicit, evidence-bound owner operation on an ACTIVE, consumed `managed_fleet_systemd` delivery: it
# changes only the EXECUTING generation of the exact active descriptor (restart -> arm -> bind). It never
# publishes, promotes, changes the descriptor, the release, the pointer or any recovery. Everything below
# is pure policy over dictionaries; a refusal carries a fixed code and at most a fixed field name.
MAINTENANCE_SCHEMA = "urn:zeus:host-delivery-active-generation:1"
MAINTENANCE_KIND = "active_generation_restart"
MAINTENANCE_REASON = "unit_environment_changed"
MAINTENANCE_ID_PREFIX = "active_generation_1:"
MAINTENANCE_ID = re.compile(r"^active_generation_1:[0-9a-f]{64}$")
MAINTENANCE_RESULT_SCHEMA = "urn:zeus:host-delivery-maintenance:1"
GENERATION_OBSERVATION_SCHEMA = "urn:zeus:managed-generation-observation:1"
MAINTENANCE_FIELDS = frozenset({"schema", "kind", "plan_id", "plan_sha256", "pin_sha256", "target_id", "release_id",
                                "descriptor_sha256", "from", "retiring", "reason", "canary_window_seconds",
                                "authority", "approved_by"})
MAINTENANCE_FROM_FIELDS = frozenset({"stage", "updated_at"})
MAINTENANCE_RETIRING_FIELDS = frozenset({"instance_id", "invocation_id", "launch_sha256"})
MAINTENANCE_WINDOW_MAX = 3600
# A systemd InvocationID: 128 bits as 32 lower-case hex digits.
INVOCATION = re.compile(r"^[0-9a-f]{32}$")
GENERATION_TRANSITIONS = {
    GENERATION_REQUESTED: frozenset({GENERATION_LAUNCHED, GENERATION_STARTED, GENERATION_FAILED}),
    GENERATION_LAUNCHED: frozenset({GENERATION_STARTED, GENERATION_FAILED}),
    GENERATION_STARTED: frozenset({GENERATION_ARMED, GENERATION_FAILED}),
    GENERATION_ARMED: frozenset({GENERATION_BOUND, GENERATION_FAILED}),
    GENERATION_BOUND: frozenset(),
    GENERATION_FAILED: frozenset(),
}
MAINTENANCE_PHASES = ("restart", "arm", "bind")
# The 21 fixed codes of INV-HOST-DELIVERY-MAINTENANCE-001 (spec D2.4); no other maintenance code exists.
MAINTENANCE_CODES = ("maintenance_invalid", "maintenance_authority_unverified", "maintenance_conflict",
                     "maintenance_not_active", "maintenance_already_used", "maintenance_phase",
                     "maintenance_target_busy", "maintenance_controller_busy", "maintenance_stale",
                     "maintenance_pause_required", "maintenance_debt_unsettled", "maintenance_invocation_mismatch",
                     "maintenance_reload_pending", "maintenance_launch_unconfirmed", "maintenance_primary_unverified",
                     "maintenance_canary_pending", "maintenance_canary_unbound", "maintenance_expired",
                     "maintenance_failed", "maintenance_admission_refused", "maintenance_reconciliation_required")
# The only codes a generation FAILS with; every other refusal leaves the last proved state in place.
MAINTENANCE_FAILURE_CODES = frozenset({"maintenance_expired", "maintenance_invocation_mismatch", "maintenance_failed"})
# How the adapter's restart authority may proceed: replace the matching intended incumbent (graceful stop,
# then one launch), launch after a proved stop, or recognize the request-bound launch already made.
RESTART_REPLACE, RESTART_LAUNCH, RESTART_RECOGNIZED = "replace", "launch", "recognized"
# The existing clock-skew rule between a wall-clock timestamp a process wrote and another clock (the PR-2
# observer's SKEW_USEC is the same two seconds).
MAINTENANCE_SKEW_SECONDS = 2
RESTART_AUTHORITY_FIELDS = frozenset({"maintenance_id", "instance_id", "invocation_id", "launch_sha256",
                                      "requested_at"})
OBSERVATION_FIELDS = frozenset({"schema", "observed_at", "running", "receipt", "receipt_present", "launch",
                                "launch_present", "launch_sha256", "launch_request_sha256",
                                "launch_request_requested_at", "target_file_matches", "control_user_matches",
                                "unit", "supervisor", "entry", "work"})
OBSERVATION_UNIT_FIELDS = frozenset({"active_state", "invocation_id", "main_pid", "exec_main_pid",
                                     "need_daemon_reload", "control_group_sha256", "environment_files_sha256",
                                     "drop_in_count"})
OBSERVATION_SUPERVISOR_FIELDS = frozenset({"pid", "state", "start_ticks", "is_main_pid"})
OBSERVATION_ENTRY_FIELDS = frozenset({"pid", "state", "start_ticks", "parent_is_supervisor", "in_unit_cgroup",
                                      "started_before_receipt"})
OBSERVATION_WORK_FIELDS = frozenset({"state", "reason_code", "active", "unresolved"})
PROCESS_STATES = frozenset({"present", "absent", "replaced", "unknown"})
WORK_STATES = frozenset({"idle", "busy", "unknown"})
ENTRY_FLAGS = ("parent_is_supervisor", "in_unit_cgroup", "started_before_receipt")
UNIT_STATE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
REASON_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
# The stages at which ANOTHER delivery of the same target competes with a maintenance for the host.
COMPETING_STAGES = POST_MERGE_OPEN | {DRAIN_INTENDED, SWITCHING, AWAITING_CONSUMPTION, ROLLING_BACK}


def _maintenance_refused(field: str):
    return DeliveryRefused("maintenance_invalid", field)


def _aware(value) -> datetime | None:
    """An aware ISO timestamp of at most 64 characters, or None."""
    if type(value) is not str or not 0 < len(value) <= 64:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def validate_active_generation(document) -> dict:
    """The owner's active-generation maintenance document, exactly (INV-HOST-DELIVERY-MAINTENANCE-001).

    Identity of the plan, pin, release, target and descriptor; the ACTIVE intent version it answers
    (`from`); the retiring host generation; the one fixed reason; the canary window; the trusted
    authority reference and the approver. There is no free-text reason, token, command, environment or
    `supersedes` field, so any extra key refuses. Its values are claims only; every defect is
    `maintenance_invalid` naming the field."""
    if not isinstance(document, dict) or set(document) != MAINTENANCE_FIELDS:
        raise _maintenance_refused("document")
    if document["schema"] != MAINTENANCE_SCHEMA:
        raise _maintenance_refused("schema")
    if document["kind"] != MAINTENANCE_KIND:
        raise _maintenance_refused("kind")
    for key in ("plan_id", "release_id", "target_id"):
        if not _token(document[key]):
            raise _maintenance_refused(key)
    for key in ("plan_sha256", "pin_sha256", "descriptor_sha256"):
        if not _hex(document[key], DIGEST_HEX):
            raise _maintenance_refused(key)
    source = document["from"]
    if not (isinstance(source, dict) and set(source) == MAINTENANCE_FROM_FIELDS and source["stage"] == ACTIVE
            and _aware(source["updated_at"]) is not None):
        raise _maintenance_refused("from")
    retiring = document["retiring"]
    if not (isinstance(retiring, dict) and set(retiring) == MAINTENANCE_RETIRING_FIELDS
            and _hex(retiring["instance_id"], INSTANCE) and _hex(retiring["invocation_id"], INVOCATION)
            and _hex(retiring["launch_sha256"], SHA256)):
        raise _maintenance_refused("retiring")
    if document["reason"] != MAINTENANCE_REASON:
        raise _maintenance_refused("reason")
    if not _bounded_int(document["canary_window_seconds"], 1, MAINTENANCE_WINDOW_MAX):
        raise _maintenance_refused("canary_window_seconds")
    if not _hex(document["authority"], EVIDENCE_REF):
        raise _maintenance_refused("authority")
    if not _hex(document["approved_by"], ACTOR_ID):
        raise _maintenance_refused("approved_by")
    return {**document, "from": dict(source), "retiring": dict(retiring)}


def generation_id(document) -> str:
    """The maintenance (= generation) id: the schema tag and the canonical digest of the validated document."""
    return MAINTENANCE_ID_PREFIX + digest(validate_active_generation(document))



def maintenance_hold(intents, target_id: str, *, exclude_plan_id=None) -> dict | None:
    """The first intent on `target_id` (other than `exclude_plan_id`) whose maintenance is open, or None."""
    for other in intents or []:
        if (isinstance(other, dict) and other.get("target_id") == target_id
                and other.get("plan_id") != exclude_plan_id and maintenance_open(other)):
            return other
    return None


def maintenance_transition(generation: dict, target: str) -> None:
    """The closed generation transition table; anything else is `maintenance_phase`."""
    state = (generation or {}).get("state")
    if target not in GENERATION_TRANSITIONS.get(state, frozenset()):
        raise DeliveryRefused("maintenance_phase", "state")


def competing_intent(other, target_id: str, plan_id: str) -> bool:
    """Another plan's intent that competes with a maintenance for this target's host.

    Deliberately NOT "non-terminal": an untouched blocked plan does not compete. It competes while it has
    merged and not settled the host, while a bound descriptor of it is unsettled (the `_predecessor_in`
    rule), while a merged verification is in flight, while it is a held migration successor, or while its
    own maintenance is open."""
    if not isinstance(other, dict) or other.get("target_id") != target_id or other.get("plan_id") == plan_id:
        return False
    stage = other.get("stage")
    unsettled = (stage in {BLOCKED, FAILED} and other.get("descriptor") is not None
                 and not (other.get("rollback") or {}).get("verified"))
    merged_verifying = stage == VERIFYING and bool(other.get("merged_revision"))
    return (stage in COMPETING_STAGES or unsettled or merged_verifying or bool(other.get("held"))
            or maintenance_open(other))


def _lease_held(lock, now: datetime) -> bool:
    lease = (lock or {}).get("lease_until")
    if not lease:
        return False
    try:
        return datetime.fromisoformat(lease) > now
    except (TypeError, ValueError):
        return True   # an unreadable lease is never read as free


def maintenance_applicable(document, *, plan_row, intent, descriptor_row, target, release_record, gate, pointer,
                           queue_row, intents, migrations, lock, now: datetime) -> tuple | None:
    """The FIRST refusal of a first maintenance request, or None when it may be requested.

    Read-only facts of one lane snapshot: the exact ACTIVE, consumed, owner-canary-qualified managed
    delivery of this plan, its bound descriptor row naming the retiring instance, the active approved
    release, the pointer and the active queue row, no competing delivery or reserving migration on the
    target and no running controller. Every refusal happens before any write or host effect."""
    doc = validate_active_generation(document)
    if target is None:
        return ("maintenance_stale", "target_id")
    if target.get("kind") != KIND_MANAGED_SYSTEMD:
        return ("maintenance_not_active", "target_id")
    plan = (plan_row or {}).get("plan") or {}
    if (plan_row or {}).get("plan_sha256") != doc["plan_sha256"]:
        return ("maintenance_stale", "plan_sha256")
    if ((plan_row or {}).get("pin") or {}).get("sha256") != doc["pin_sha256"]:
        return ("maintenance_stale", "pin_sha256")
    for key in ("plan_id", "release_id", "target_id"):
        if plan.get(key) != doc[key]:
            return ("maintenance_stale", key)
    if target.get("target_id") != doc["target_id"]:
        return ("maintenance_stale", "target_id")
    if plan.get("canary_check_id") != CANARY_FLEET:
        return ("maintenance_not_active", "canary_check_id")
    if not isinstance(intent, dict) or intent.get("stage") != ACTIVE:
        return ("maintenance_not_active", "stage")
    if intent.get("outcome") != OUTCOME_ACTIVE or (intent.get("canary") or {}).get("passed") is not True:
        return ("maintenance_not_active", "canary")
    if doc["from"] != {"stage": ACTIVE, "updated_at": intent.get("updated_at")}:
        return ("maintenance_stale", "from")
    descriptor = intent.get("descriptor")
    if (doc["descriptor_sha256"] != intent.get("descriptor_sha256") or not isinstance(descriptor, dict)
            or descriptor_digest(descriptor) != intent.get("descriptor_sha256")):
        return ("maintenance_stale", "descriptor_sha256")
    row = descriptor_row if isinstance(descriptor_row, dict) else None
    if (row is None or row.get("descriptor_sha256") != doc["descriptor_sha256"] or row.get("consumed") is not True
            or row.get("rolled_back") or row.get("plan_id") != doc["plan_id"]):
        return ("maintenance_not_active", "descriptor_row")
    if not (row.get("instance_id") == row.get("observed_instance_id") == intent.get("instance_id")
            == doc["retiring"]["instance_id"]):
        return ("maintenance_invocation_mismatch", "instance_id")
    if (release_record or {}).get("status") != "active" or (gate or {}).get("state") != "approved":
        return ("maintenance_not_active", "release_id")
    if (pointer or {}).get("release_id") != doc["release_id"]:
        return ("maintenance_not_active", "pointer")
    if not isinstance(queue_row, dict) or queue_row.get("status") != "active":
        return ("maintenance_not_active", "queue")
    if any(competing_intent(other, doc["target_id"], doc["plan_id"]) for other in intents or []):
        return ("maintenance_target_busy", "target_id")
    if any(isinstance(m, dict) and m.get("target_id") == doc["target_id"] and m.get("state") in MIGRATION_RESERVING
           for m in migrations or []):
        return ("maintenance_target_busy", "target_id")
    if _lease_held(lock, now):
        return ("maintenance_controller_busy", "controller")
    return None


def fleet_ready_refusal(readiness, *, maintenance_id: str, own_job_id=None) -> tuple | None:
    """The Fleet as a maintenance needs it: registered, OWNER-paused with no activation hold, no reserving
    job but this generation's own, no held execution unit and no other open maintenance permit. Unknown
    debt is never settled."""
    if not isinstance(readiness, dict) or readiness.get("registered") is not True:
        return ("maintenance_debt_unsettled", "fleet")
    if readiness.get("owner_paused") is not True or readiness.get("activation_hold") is not False:
        return ("maintenance_pause_required", "fleet")
    reserving, units, permits = (readiness.get("reserving"), readiness.get("units_held"),
                                 readiness.get("open_permits"))
    if not (isinstance(reserving, list) and isinstance(units, list) and isinstance(permits, list)):
        return ("maintenance_debt_unsettled", "fleet")
    if set(reserving) - {own_job_id} or units:
        return ("maintenance_debt_unsettled", "fleet")
    if set(permits) - {maintenance_id}:
        return ("maintenance_debt_unsettled", "fleet")
    return None


def _nullable(value, check) -> bool:
    return value is None or check(value)


def _flag(value) -> bool:
    return value is None or type(value) is bool


def _count(value, low: int = 0) -> bool:
    return type(value) is int and low <= value <= 2 ** 63 - 1


def _observation_part(value, fields, name: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise DeliveryRefused("maintenance_invocation_mismatch", "observation")
    return dict(value)


def validate_generation_observation(observation) -> dict:
    """The adapter's read-only generation observation, checked as untrusted data (exact keys and types).

    A missing fact is `None`, never a guess. The receipt is replaced by its validated copy when valid;
    otherwise it is `None` and `receipt_state` names why (`absent` or `unreadable`). Any defect is
    `maintenance_invocation_mismatch` naming `observation`."""
    def bad():
        return DeliveryRefused("maintenance_invocation_mismatch", "observation")

    if not isinstance(observation, dict) or set(observation) != OBSERVATION_FIELDS:
        raise bad()
    if observation["schema"] != GENERATION_OBSERVATION_SCHEMA or _aware(observation["observed_at"]) is None:
        raise bad()
    for key in ("running", "control_user_matches"):
        if not _flag(observation[key]):
            raise bad()
    for key in ("receipt_present", "launch_present", "target_file_matches"):
        if type(observation[key]) is not bool:
            raise bad()
    receipt, launch = observation["receipt"], observation["launch"]
    if not (receipt is None or isinstance(receipt, dict)) or not (launch is None or isinstance(launch, dict)):
        raise bad()
    launch_sha256 = observation["launch_sha256"]
    if (launch is None) != (launch_sha256 is None) or (launch is not None and launch_sha256 != digest(launch)):
        raise bad()
    if not _nullable(observation["launch_request_sha256"], lambda v: _hex(v, SHA256)):
        raise bad()
    if not _nullable(observation["launch_request_requested_at"], lambda v: _aware(v) is not None):
        raise bad()
    unit = _observation_part(observation["unit"], OBSERVATION_UNIT_FIELDS, "unit")
    if not (_nullable(unit["active_state"], lambda v: _hex(v, UNIT_STATE))
            and _nullable(unit["invocation_id"], lambda v: _hex(v, INVOCATION))
            and _nullable(unit["main_pid"], lambda v: _count(v, 1))
            and _nullable(unit["exec_main_pid"], _count) and _flag(unit["need_daemon_reload"])
            and _nullable(unit["control_group_sha256"], lambda v: _hex(v, SHA256))
            and _nullable(unit["environment_files_sha256"], lambda v: _hex(v, SHA256))
            and _nullable(unit["drop_in_count"], _count)):
        raise bad()
    processes = {}
    for name, fields, flags in (("supervisor", OBSERVATION_SUPERVISOR_FIELDS, ("is_main_pid",)),
                                ("entry", OBSERVATION_ENTRY_FIELDS, ENTRY_FLAGS)):
        part = _observation_part(observation[name], fields, name)
        if not (_nullable(part["pid"], lambda v: _count(v, 1)) and part["state"] in PROCESS_STATES
                and _nullable(part["start_ticks"], _count) and all(_flag(part[flag]) for flag in flags)):
            raise bad()
        processes[name] = part
    work = _observation_part(observation["work"], OBSERVATION_WORK_FIELDS, "work")
    if not (work["state"] in WORK_STATES and _nullable(work["reason_code"], lambda v: _hex(v, REASON_CODE))
            and _nullable(work["active"], _count) and _nullable(work["unresolved"], _count)):
        raise bad()
    named = receipt_identity(receipt, present=observation["receipt_present"])
    return {**{key: observation[key] for key in OBSERVATION_FIELDS - {"receipt", "launch", "unit", "supervisor",
                                                                      "entry", "work"}},
            "receipt": validate_receipt(receipt) if named["state"] == "valid" else None,
            "receipt_state": named["state"], "launch": copy.deepcopy(launch), "unit": unit,
            "supervisor": processes["supervisor"], "entry": processes["entry"], "work": work}


def validate_restart_authority(restarts) -> dict:
    """The narrowly typed restart authority `HostTargetBase.start(restarts=)` is handed, exactly."""
    if not (isinstance(restarts, dict) and set(restarts) == RESTART_AUTHORITY_FIELDS
            and _hex(restarts["maintenance_id"], MAINTENANCE_ID) and _hex(restarts["instance_id"], INSTANCE)
            and _hex(restarts["invocation_id"], INVOCATION) and _hex(restarts["launch_sha256"], SHA256)
            and _aware(restarts["requested_at"]) is not None):
        raise DeliveryRefused("maintenance_invalid", "restarts")
    return dict(restarts)


def _decision(path=None, reason_code=None, field=None) -> dict:
    return {"path": path, "reason_code": reason_code, "field": field}


def classify_restart(descriptor: dict, observation, restarts) -> dict:
    """Which restart path the observed host allows for this exact authority, or the first refusal.

    `replace`: the controller-state is still the retiring launch and the running instance is EXACTLY the
    recorded incumbent (its consumed receipt, its unit invocation and launch, a supervisor that is the
    unit's main pid, an entry that is its child in its control group and started before its receipt, and
    idle work). `launch`: the same retiring launch, positively stopped (no other instance, receipt absent
    or the retiring one, the unit not active under another invocation) and no launch request of this or a
    later request persisted (S2R F1: such a request is a start of unproven outcome, held). `recognized`: the
    controller-state changed to a launch of this descriptor under a NEW invocation, started after the
    request, whose persisted launch request carries exactly this request's time, and which the unit is
    running now.
    Anything else refuses before any effect; an arbitrary changed launch (a reboot, an unrecorded N1
    replacement) is never adopted."""
    try:
        authority = validate_restart_authority(restarts)
        observed = validate_generation_observation(observation)
    except DeliveryRefused as exc:
        return _decision(None, exc.reason_code, exc.field)
    unit, supervisor, entry = observed["unit"], observed["supervisor"], observed["entry"]
    if observed["control_user_matches"] is not True:
        return _decision(None, "maintenance_invalid", "service_user")
    if observed["target_file_matches"] is not True:
        return _decision(None, "maintenance_stale", "target_file")
    if unit["need_daemon_reload"] is not False:
        return _decision(None, "maintenance_reload_pending", "unit")
    running = observed["running"]
    if running is None:
        return _decision(None, "maintenance_launch_unconfirmed", "running")
    receipt, launch = observed["receipt"], observed["launch"]
    consumed = receipt is not None and consumption_verdict(descriptor, receipt)["consumed"]
    names_retiring = consumed and receipt["instance_id"] == authority["instance_id"]
    if observed["launch_sha256"] == authority["launch_sha256"]:
        if running:
            if unit["invocation_id"] != authority["invocation_id"]:
                # N1: the unit runs another invocation than the recorded incumbent's.
                return _decision(None, "maintenance_invocation_mismatch", "invocation_id")
            if not names_retiring:
                return _decision(None, "maintenance_invocation_mismatch", "instance_id")
            if launch.get("invocation_id") != authority["invocation_id"]:
                return _decision(None, "maintenance_invocation_mismatch", "launch")
            if supervisor["is_main_pid"] is not True:
                return _decision(None, "maintenance_invocation_mismatch", "supervisor")
            if not all(entry[flag] is True for flag in ENTRY_FLAGS):
                # PID reuse, a wrong parent or another control group: not the recorded incumbent.
                return _decision(None, "maintenance_invocation_mismatch", "entry")
            if observed["work"]["state"] != "idle":
                return _decision(None, "maintenance_debt_unsettled", "work")
            return _decision(RESTART_REPLACE)
        absent = receipt is None and observed["receipt_state"] == "absent"
        if ((absent or names_retiring) and unit["invocation_id"] in (None, authority["invocation_id"])
                and unit["active_state"] in (None, "inactive", "failed")):
            # S2R F1: the one launch of THIS request persists its launch request (stamped with the request's
            # own time) BEFORE its start. Such a request (or any launch request not older than this
            # maintenance request) with the controller-state still the retiring launch means a start whose
            # outcome is unproven: hold, never launch a second time. An unreadable request proves nothing.
            request_at = _aware(observed["launch_request_requested_at"])
            if request_at is None or request_at >= _aware(authority["requested_at"]):
                return _decision(None, "maintenance_launch_unconfirmed", "launch")
            return _decision(RESTART_LAUNCH)
        return _decision(None, "maintenance_invocation_mismatch", "instance_id")
    requested = _aware(authority["requested_at"])
    started = _aware((launch or {}).get("started_at")) if isinstance(launch, dict) else None
    request_at = _aware(observed["launch_request_requested_at"])
    # Recognition is bound to THIS attempt: the persisted launch request carries exactly the request's time.
    if (isinstance(launch, dict) and launch.get("descriptor_sha256") == descriptor_digest(descriptor)
            and _hex(launch.get("invocation_id"), INVOCATION) and launch["invocation_id"] != authority["invocation_id"]
            and started is not None and started >= requested and request_at is not None
            and request_at == requested and unit["invocation_id"] == launch["invocation_id"]):
        return _decision(RESTART_RECOGNIZED)
    return _decision(None, "maintenance_launch_unconfirmed", "launch")


def new_generation_refusal(descriptor: dict, observation, generation: dict) -> tuple | None:
    """Whether the live identity is EXACTLY the started generation, or the first refusal.

    A definite difference (the started instance stopped, another receipt, invocation, launch, or a
    process identity flag that is False) is `maintenance_invocation_mismatch`, which the caller turns into
    a generation failure. An UNKNOWN fact (liveness, receipt, unit or a flag not observable) is
    `maintenance_launch_unconfirmed` and keeps the last proved state (spec D2.2: uncertainty is a named
    reason, not an automatic failure). A pending daemon reload is `maintenance_reload_pending`."""
    try:
        observed = validate_generation_observation(observation)
    except DeliveryRefused:
        # An unreadable observation is not evidence that the generation changed.
        return ("maintenance_launch_unconfirmed", "observation")
    launched = (generation or {}).get("launched") or {}
    started = launched.get("receipt") or {}
    retiring = (generation or {}).get("retiring") or {}
    unit = observed["unit"]
    if observed["running"] is None:
        return ("maintenance_launch_unconfirmed", "running")
    if observed["running"] is not True:
        return ("maintenance_invocation_mismatch", "running")
    if observed["receipt"] is None:
        return ("maintenance_launch_unconfirmed", "receipt")
    verdict = consumption_verdict(descriptor, observed["receipt"], expected_instance=retiring.get("instance_id"))
    if not verdict["consumed"]:
        return ("maintenance_invocation_mismatch", "receipt")
    if verdict["instance_id"] != started.get("instance_id"):
        return ("maintenance_invocation_mismatch", "instance_id")
    if unit["invocation_id"] is None:
        return ("maintenance_launch_unconfirmed", "unit")
    if unit["invocation_id"] != launched.get("invocation_id"):
        return ("maintenance_invocation_mismatch", "invocation_id")
    if observed["launch_sha256"] is None:
        return ("maintenance_launch_unconfirmed", "launch")
    if observed["launch_sha256"] != launched.get("launch_sha256"):
        return ("maintenance_invocation_mismatch", "launch")
    for name, flags in (("supervisor", ("is_main_pid",)), ("entry", ENTRY_FLAGS)):
        values = [observed[name][flag] for flag in flags]
        if any(value is False for value in values):
            return ("maintenance_invocation_mismatch", name)
        if any(value is not True for value in values):
            return ("maintenance_launch_unconfirmed", name)
    if unit["need_daemon_reload"] is not False:
        return ("maintenance_reload_pending", "unit")
    return None


def selection_of(observation: dict) -> dict:
    """The unit's source-selection provenance: the digest of its environment files and its drop-in count."""
    unit = (observation or {}).get("unit") or {}
    return {"environment_files_sha256": unit.get("environment_files_sha256"),
            "drop_in_count": unit.get("drop_in_count")}


__all__ = ["COMPETING_STAGES", "GENERATION_ARMED", "GENERATION_BOUND", "GENERATION_FAILED", "GENERATION_LAUNCHED",
           "GENERATION_OBSERVATION_SCHEMA", "GENERATION_REQUESTED", "GENERATION_STARTED", "GENERATION_STATES",
           "GENERATION_TRANSITIONS", "INVOCATION", "MAINTENANCE_CODES", "MAINTENANCE_FAILURE_CODES",
           "MAINTENANCE_FIELDS", "MAINTENANCE_FROM_FIELDS", "MAINTENANCE_ID", "MAINTENANCE_ID_PREFIX",
           "MAINTENANCE_KIND", "MAINTENANCE_PHASES", "MAINTENANCE_REASON", "MAINTENANCE_RESULT_SCHEMA",
           "MAINTENANCE_RETIRING_FIELDS", "MAINTENANCE_SCHEMA", "MAINTENANCE_SKEW_SECONDS", "MAINTENANCE_WINDOW_MAX",
           "NEXT_PHASE", "RESTART_LAUNCH", "RESTART_RECOGNIZED", "RESTART_REPLACE", "classify_restart",
           "competing_intent", "fleet_ready_refusal", "generation_id", "maintenance_applicable", "maintenance_hold",
           "maintenance_of", "maintenance_open", "maintenance_transition", "maintenance_view",
           "new_generation_refusal", "selection_of", "validate_active_generation", "validate_generation_observation",
           "validate_restart_authority"]
