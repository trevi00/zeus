"""The managed `limited_active` observation: pure checks of the read-only receipt producer.

@invariant INV-HOST-MIGRATION-001

INV-HOST-MIGRATION-001 keeps HOST LAUNCH AUTHORITY (the effective activation, including a recorded
successor) apart from the CONSUMED MANAGED PAYLOAD (a HostDelivery descriptor, INV-HOST-DELIVERY-001).
`adapters.host_migration_evidence` reads the coordinator record, the launcher files, one systemd unit,
its journal, `/proc` and read-only store projections; this module decides over the facts it is handed.
It holds no file, process, journal or store access. Every refusal is a `MigrationRefused` whose
`reason_code` is one fixed producer code and whose `field` is one fixed diagnostic token, never a
value and never an exception text.

The observation (`urn:zeus:host-migration-managed-observation:1`) has exactly the keys of
`OBSERVATION_FIELDS`. Each source is `{sha256, observed_at}` over a sanitized projection the wrapper
archives beside it. The canonical digest of the observation (`domain.model.digest`, the canonical JSON
convention) is the `result_sha256` of three existing `evidence_receipt` objects: `(host-activation,
<effective id>)`, `(service-startup, descriptor=<recomputed digest>)` and `(observation,
canary=<plan>:instance=<instance>)`. They carry exit 0 / ok only on complete success. A failure keeps
its fixed code and never gets a success receipt. The transition draft is data for the operator; nothing
here records it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from codex_harness.domain.host_delivery import (
    ACTIVE,
    CANARY_FLEET,
    INSTANCE,
    KIND_MANAGED_SYSTEMD,
    MANAGED_SYSTEMD_UNIT,
    MANAGED_TARGET_FIELDS,
    OWNER_CANARY_RECEIPT_SCHEMA,
    POST_MERGE_OPEN,
    REGISTRY_SCHEMA,
    DeliveryRefused,
    canary_request_matches,
    consumption_verdict,
    descriptor_digest,
    plan_digest,
    same_path,
    validate_descriptor,
    validate_plan,
    validate_targets,
)
from codex_harness.domain.host_migration import (
    COMMIT,
    HEX64,
    IMAGE_DIGEST,
    LIMITED_ACTIVE,
    OBSERVATION,
    RESTORED_PAUSED,
    TOKEN,
    TRANSITION_SCHEMA,
    UTC,
    MigrationRefused,
    activation_receipt,
    effective_activation,
    evidence_receipt,
    managed_canary_subject,
    managed_consumption_subject,
    manifest_digest,
    validate_managed_lineage,
    validate_manifest,
    validate_transition,
)
from codex_harness.domain.managed_runtime import check_runtime_path
from codex_harness.domain.model import canonical, digest
from codex_harness.domain.owner_actions import COMPLETED, DELIVERY_CANARY, VERDICT_ACCEPTED

OBSERVATION_SCHEMA = "urn:zeus:host-migration-managed-observation:1"
OBSERVATION_FIELDS = ("schema", "migration_id", "manifest_sha256", "observed_from", "observed_to", "activation",
                      "lineage", "checks", "sources", "ok", "reason_code")
ACTIVATION_FIELDS = ("id", "release_revision", "image", "profile_sha256", "document_sha256")
CHECKS = ("activation_equal", "current_equal", "launch_bound", "process_bound", "consumption", "canary_bound",
          "stable_capture")
SOURCES = ("migration", "activation_file", "launch", "supervisor", "entry", "descriptor", "startup", "delivery",
           "canary_receipt", "canary_record")
SOURCE_FIELDS = {"sha256", "observed_at"}

# The producer's refusal codes (INV-HOST-MIGRATION-001). The diagnostic token beside one is a fixed
# code too, e.g. the incumbent consumption reason (`receipt_stale_instance`).
UNAVAILABLE = "activation_observation_unavailable"
DOCUMENT = "activation_document_mismatch"
LAUNCH = "activation_launch_unbound"
PROCESS = "activation_process_unbound"
CONSUMPTION = "activation_consumption_refused"
CANARY = "activation_canary_unbound"
CHANGED = "activation_observation_changed"
REFUSALS = (UNAVAILABLE, DOCUMENT, LAUNCH, PROCESS, CONSUMPTION, CANARY, CHANGED)
# A malformed observation document: the producer's own output is refused before any receipt exists.
INVALID = "observation_invalid"
DIAGNOSTIC = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,79}$")

# The launcher's fixed `launch` event (deploy/aibox/zeus_aibox_service.py `launch`): emitted BEFORE the
# exec, and emitted by a dry run as well, so the event alone never proves a launch.
LAUNCH_EVENT_FIELDS = {"event", "role", "revision", "migration_id"}
LAUNCH_ROLE = "managed-fleet"
MANAGED_UNIT = MANAGED_SYSTEMD_UNIT + ".service"
MANAGED_MODULE = "codex_harness.adapters.managed_runtime"
ENTRY_WORKLOAD = "fleet"
# A process start is known to one clock tick; systemd records ExecMainStartTimestamp right after its fork.
FORK_WINDOW_USEC = 5_000_000
# Tolerance between the journal's monotonic/realtime pair and a wall-clock timestamp a process wrote.
SKEW_USEC = 2_000_000
CANARY_RECEIPT_FIELDS = {"schema", "descriptor_sha256", "instance_id", "passed", "evidence", "reason_code",
                         "recorded_at"}
INTENT_FIELDS = ("plan_id", "target_id", "plan_sha256", "stage", "revision", "descriptor", "descriptor_sha256",
                 "previous_descriptor_sha256", "previous_instance_id", "instance_id", "candidate_instance_id",
                 "canary", "rollback", "updated_at")
DESCRIPTOR_ROW_FIELDS = ("target_id", "descriptor", "descriptor_sha256", "consumed", "startup_observed",
                         "observed_instance_id", "observed_revision", "instance_id", "plan_id", "release_id",
                         "rolled_back", "updated_at")
RECORD_FIELDS = ("id", "kind", "state", "reason_code", "binding", "binding_sha256", "outcome", "version",
                 "updated_at")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def refused(code: str, detail: str) -> MigrationRefused:
    return MigrationRefused(code, detail)


def diagnostic(detail) -> str:
    """A fixed token or `unknown`: nothing else ever reaches archived failure evidence."""
    return detail if type(detail) is str and DIAGNOSTIC.fullmatch(detail) else "unknown"


def utc_from_usec(microseconds: int) -> str:
    return (EPOCH + timedelta(microseconds=microseconds)).isoformat()


def usec_of(value) -> int | None:
    """Microseconds since the epoch of an aware ISO timestamp, or None."""
    if type(value) is not str:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    delta = moment - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def source(projection, observed_at: str) -> dict:
    """One `sources` entry: the digest of the archived projection and when it was read."""
    return {"sha256": digest(projection), "observed_at": observed_at}


# ----- the coordinator record and the launcher files ----------------------------------------------------
def migration_view(row: dict) -> dict:
    """The coordinator row as the observation binds it: state, exact manifest, effective head and the
    launcher document derived from that head in `restored_paused`. It is the `migration` projection."""
    try:
        manifest = validate_manifest(row["manifest"])
        exact = type(row["manifest_sha256"]) is str and manifest_digest(manifest) == row["manifest_sha256"]
        host = manifest["target"]["host_id"]
    except MigrationRefused:
        exact, host = False, None
    history = list(row.get("history") or [])
    view = {"migration_id": row["migration_id"], "state": row["state"], "manifest_sha256": row["manifest_sha256"],
            "manifest_exact": exact, "target_host_id": host, "transitions": len(history),
            "history_sha256": digest(history), "effective": None, "document": None}
    intent = row.get("activation_intent")
    if intent is not None:
        head = effective_activation(intent, list(row.get("activation_successors") or []))
        activation = head["activation"]
        view["effective"] = {"id": head["id"], "kind": head["kind"], "host_id": activation["host_id"],
                             "release_revision": activation["release_revision"], "image": activation["image"],
                             "profile_sha256": activation["profile_sha256"],
                             "predecessor_id": activation.get("predecessor_id")}
        if exact:
            view["document"] = activation_receipt(activation, row["manifest_sha256"], RESTORED_PAUSED)
    return view


def require_head(view: dict, migration_id: str, expected_id: str) -> dict:
    """Restored-paused, exact manifest, and the effective head is exactly the expected one. Returns the
    observation's `activation` block."""
    if view["migration_id"] != migration_id:
        raise refused(DOCUMENT, "migration_id")
    if not view["manifest_exact"]:
        raise refused(DOCUMENT, "manifest")
    if view["state"] != RESTORED_PAUSED:
        raise refused(DOCUMENT, "migration_state")
    if view["effective"] is None:
        raise refused(DOCUMENT, "activation_intent_missing")
    if view["effective"]["id"] != expected_id:
        raise refused(DOCUMENT, "activation_head_moved")
    effective = view["effective"]
    return {"id": effective["id"], "release_revision": effective["release_revision"], "image": effective["image"],
            "profile_sha256": effective["profile_sha256"], "document_sha256": digest(view["document"])}


def require_activation_file(projection: dict, view: dict) -> None:
    """`host-activation.json` equals `activation_receipt(effective, manifest, restored_paused)` AS AN
    OBJECT (types included), and no host fence exists."""
    if projection["fence"]:
        raise refused(DOCUMENT, "host_fenced")
    if not isinstance(projection["document"], dict) or canonical(projection["document"]) != canonical(view["document"]):
        raise refused(DOCUMENT, "activation_file")


def require_current(projection: dict, view: dict) -> None:
    """`releases/current` resolves to the effective activation's revision directory."""
    if projection["current"] != view["effective"]["release_revision"] or projection["release_present"] is not True:
        raise refused(DOCUMENT, "current")


# ----- the unit, its journal and its processes ---------------------------------------------------------
UNIT_PROPERTIES = ("ActiveState", "SubState", "MainPID", "ExecMainPID", "InvocationID", "ControlGroup",
                   "ExecMainStartTimestampMonotonic")


def unit_facts(text) -> dict:
    """`systemctl show -p ...` output as typed facts; anything unreadable is an unknown."""
    facts = dict(line.split("=", 1) for line in str(text or "").splitlines() if "=" in line)
    numbers = {}
    for key in ("MainPID", "ExecMainPID", "ExecMainStartTimestampMonotonic"):
        value = facts.get(key)
        if not (type(value) is str and value.isascii() and value.isdigit()):
            raise refused(UNAVAILABLE, "unit")
        numbers[key] = int(value)
    invocation, group = facts.get("InvocationID"), facts.get("ControlGroup")
    if not (type(invocation) is str and re.fullmatch(r"[0-9a-f]{32}", invocation)):
        raise refused(UNAVAILABLE, "unit")
    if not (type(group) is str and group.startswith("/") and ".." not in group.split("/")):
        raise refused(UNAVAILABLE, "unit")
    return {"active_state": facts.get("ActiveState"), "sub_state": facts.get("SubState"),
            "main_pid": numbers["MainPID"], "exec_main_pid": numbers["ExecMainPID"], "invocation_id": invocation,
            "control_group": group, "exec_main_start_usec": numbers["ExecMainStartTimestampMonotonic"]}


def _journal_number(entry: dict, key: str) -> int:
    value = entry.get(key)
    if not (type(value) is str and value.isascii() and value.isdigit()):
        raise refused(UNAVAILABLE, "journal_entry")
    return int(value)


def launch_record(entries, *, unit: str, invocation_id: str, boot_id: str, main_pid: int) -> dict:
    """The ONE launcher document the unit's main process wrote to its journal in this invocation.

    journald stores each line of the launcher's indented JSON as one entry, so the document is
    reassembled from the lines of the main process's own stream (`_PID`, `_STREAM_ID`), from a line
    that is exactly `{` to one that is exactly `}`. Only the main process counts. The launcher emits
    `launch` and then execs in place, so its pid IS the unit's main pid. A dry run, or any process
    other than the main one, cannot supply the event. A `launch_refused` event, two launch events, or
    a line from another boot, invocation, unit or transport refuses."""
    pid, open_documents, documents = str(main_pid), {}, []
    for entry in entries:
        if not isinstance(entry, dict):
            raise refused(UNAVAILABLE, "journal_entry")
        message = entry.get("MESSAGE")
        if entry.get("_PID") != pid or type(message) is not str:
            continue
        stream = entry.get("_STREAM_ID")
        if stream not in open_documents:
            if message == "{":
                open_documents[stream] = [entry]
            elif message.startswith("{") and message.endswith("}"):
                documents.append([entry])
            continue
        open_documents[stream].append(entry)
        if message == "}":
            documents.append(open_documents.pop(stream))
    parsed = []
    for lines in documents:
        try:
            document = json.loads("\n".join(line["MESSAGE"] for line in lines))
        except ValueError:
            continue
        if isinstance(document, dict) and "event" in document:
            parsed.append((document, lines))
    if any(document.get("event") == "launch_refused" for document, _ in parsed):
        raise refused(LAUNCH, "launch_refused")
    launches = [(document, lines) for document, lines in parsed if document.get("event") == "launch"]
    if not launches:
        raise refused(LAUNCH, "launch_missing")
    if len(launches) > 1:
        raise refused(LAUNCH, "launch_ambiguous")
    document, lines = launches[0]
    for line in lines:
        if line.get("_BOOT_ID") != boot_id:
            raise refused(LAUNCH, "launch_boot")
        if line.get("_SYSTEMD_INVOCATION_ID") != invocation_id:
            raise refused(LAUNCH, "launch_invocation")
        if line.get("_SYSTEMD_UNIT") != unit:
            raise refused(LAUNCH, "launch_unit")
        if line.get("_TRANSPORT") != "stdout":
            raise refused(LAUNCH, "launch_transport")
    first = lines[0]
    cursor = first.get("__CURSOR")
    if not (type(cursor) is str and 0 < len(cursor) <= 400):
        raise refused(UNAVAILABLE, "journal_entry")
    realtime = _journal_number(first, "__REALTIME_TIMESTAMP")
    return {"unit": unit, "boot_id": boot_id, "invocation_id": invocation_id, "pid": main_pid, "cursor": cursor,
            "monotonic_usec": _journal_number(first, "__MONOTONIC_TIMESTAMP"), "realtime_usec": realtime,
            "at": utc_from_usec(realtime), "lines": len(lines), "event": document}


def require_launch(record: dict, unit: dict, supervisor: dict, *, migration_id: str, revision: str) -> None:
    """A real launch of THIS activation that happened inside THIS invocation's main process: the fixed
    event fields, then its time after the unit's exec-main start and after that process began."""
    event = record["event"]
    if set(event) != LAUNCH_EVENT_FIELDS:
        raise refused(LAUNCH, "launch_fields")
    if event["role"] != LAUNCH_ROLE:
        raise refused(LAUNCH, "launch_role")
    if event["migration_id"] != migration_id:
        raise refused(LAUNCH, "launch_migration")
    if event["revision"] != revision:
        raise refused(LAUNCH, "launch_revision")
    if record["monotonic_usec"] < unit["exec_main_start_usec"]:
        raise refused(LAUNCH, "launch_before_invocation")
    if supervisor.get("state") != "present" or record["monotonic_usec"] < supervisor["start_usec"]:
        raise refused(LAUNCH, "launch_before_process")


def require_supervisor(unit: dict, supervisor: dict, *, argv: list) -> None:
    """The unit's main process is the supervisor the launcher exec'd: running unit, main pid, its
    cgroup, direct child of the service manager, the exact supervise argv of the activation release,
    and a start inside the fork window of the unit's exec-main start (a reused pid starts later)."""
    if unit["active_state"] != "active" or unit["sub_state"] != "running":
        raise refused(PROCESS, "unit_not_running")
    if unit["main_pid"] <= 0 or unit["main_pid"] != unit["exec_main_pid"]:
        raise refused(PROCESS, "main_pid")
    if supervisor.get("state") != "present":
        raise refused(PROCESS, "supervisor_" + str(supervisor.get("state")))
    if supervisor["cgroup"] != unit["control_group"]:
        raise refused(PROCESS, "supervisor_cgroup")
    if supervisor["ppid"] != 1:
        raise refused(PROCESS, "supervisor_parent")
    if supervisor["argv"] != argv:
        raise refused(PROCESS, "supervisor_argv")
    start, main = supervisor["start_usec"], unit["exec_main_start_usec"]
    if start > main + supervisor["tick_usec"] or main - start > FORK_WINDOW_USEC:
        raise refused(PROCESS, "supervisor_start")


def supervisor_launches(text, invocation_id: str) -> list:
    """The lines `managed_runtime.supervise` journaled for THIS unit invocation, in order."""
    lines = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        document = json.loads(line)
        if not isinstance(document, dict):
            raise refused(UNAVAILABLE, "supervisor_journal")
        if document.get("invocation_id") == invocation_id:
            lines.append(document)
    return lines


def require_supervisor_launch(lines: list, *, descriptor_sha256: str) -> None:
    """The supervisor of this invocation re-validated the request, descriptor, seal and Fleet gate and
    launched exactly the consumed descriptor's real Fleet workload, once, with no refusal."""
    if any(line.get("event") == "refused" for line in lines):
        raise refused(PROCESS, "supervisor_refused")
    launches = [line for line in lines if line.get("event") == "launch"]
    if len(launches) != 1:
        raise refused(PROCESS, "supervisor_launch_missing" if not launches else "supervisor_launch_ambiguous")
    if launches[0].get("descriptor_sha256") != descriptor_sha256 or launches[0].get("workload") != ENTRY_WORKLOAD:
        raise refused(PROCESS, "supervisor_descriptor")


def require_entry(entry: dict, supervisor: dict, unit: dict, launch: dict, *, argv: list, started_at) -> None:
    """The live managed entry is the process whose startup receipt is consumed. It is the supervisor's
    child in the unit cgroup with the registered interpreter's entry argv. It started after the
    supervisor and no later than the receipt it wrote, and after this launch. The interpreter prefix
    is the target's registered one, not the launcher revision: the sealed runtime is the provenance."""
    if entry.get("state") != "present":
        raise refused(PROCESS, "entry_" + str(entry.get("state")))
    if entry["ppid"] != supervisor["pid"]:
        raise refused(PROCESS, "entry_parent")
    if entry["cgroup"] != unit["control_group"]:
        raise refused(PROCESS, "entry_cgroup")
    if entry["argv"] != argv:
        raise refused(PROCESS, "entry_argv")
    if entry["start_ticks"] < supervisor["start_ticks"]:
        raise refused(PROCESS, "entry_start")
    started = usec_of(started_at)
    if started is None:
        raise refused(PROCESS, "startup_time")
    wall = launch["realtime_usec"] - launch["monotonic_usec"] + entry["start_usec"]
    if wall > started + SKEW_USEC:
        # The receipt predates this process: it was written by another one under the same pid.
        raise refused(PROCESS, "entry_after_startup")
    if started + SKEW_USEC < launch["realtime_usec"]:
        raise refused(PROCESS, "startup_before_launch")


# ----- the consumed managed payload (INV-HOST-DELIVERY-001) ---------------------------------------------
def delivery_view(target_row, plan_row, intent, descriptor_row, intents, *, target_id: str, plan_id: str) -> dict:
    """The `delivery` projection: the typed binding fields the comparisons below repeat."""
    for row, name in ((target_row, "delivery_target"), (plan_row, "delivery_plan"), (intent, "delivery_intent"),
                      (descriptor_row, "delivery_descriptor")):
        if not isinstance(row, dict):
            raise refused(UNAVAILABLE, name)
    open_plans = sorted(str(other.get("plan_id")) for other in intents or []
                        if isinstance(other, dict) and other.get("target_id") == target_id
                        and other.get("plan_id") != plan_id and other.get("stage") in POST_MERGE_OPEN)
    return {"target": {key: target_row.get(key) for key in sorted(MANAGED_TARGET_FIELDS)},
            "plan": {"plan_id": plan_row.get("plan_id"), "plan_sha256": plan_row.get("plan_sha256"),
                     "plan": plan_row.get("plan")},
            "intent": {key: intent.get(key) for key in INTENT_FIELDS},
            "descriptor_row": {key: descriptor_row.get(key) for key in DESCRIPTOR_ROW_FIELDS},
            "open_plans": open_plans}


def require_consumption(view: dict, descriptor_document, receipt, activation: dict, *, target_id: str,
                        plan_id: str, state_dir: str) -> dict:
    """The registered target, the delivery of exactly this plan and the descriptor on the host agree,
    and the EXISTING `consumption_verdict` accepts the startup receipt.

    `expected_instance` is the delivery's PREVIOUS instance, exactly as HostDelivery consumed it
    (INV-HOST-DELIVERY-001): supplying the current one would refuse it by design. The instance the
    verdict returns must then separately be the delivery's bound and observed instance. Descriptor
    image and profile must be the activation's. The payload revision stays the descriptor's."""
    try:
        target = validate_targets({"schema": REGISTRY_SCHEMA, "targets": [view["target"]]})["targets"][0]
    except DeliveryRefused:
        raise refused(CONSUMPTION, "target_invalid") from None
    if target["target_id"] != target_id or target["kind"] != KIND_MANAGED_SYSTEMD \
            or target["service"] != MANAGED_SYSTEMD_UNIT or not same_path(target["state_dir"], state_dir):
        raise refused(CONSUMPTION, "target_binding")
    try:
        plan = validate_plan(view["plan"]["plan"])
    except DeliveryRefused:
        raise refused(CONSUMPTION, "plan_invalid") from None
    plan_sha256 = view["plan"]["plan_sha256"]
    if plan_digest(plan) != plan_sha256 or plan["plan_id"] != plan_id or plan["target_id"] != target_id:
        raise refused(CONSUMPTION, "plan_binding")
    try:
        descriptor = validate_descriptor(descriptor_document)
        check_runtime_path(target, descriptor)
    except DeliveryRefused as exc:
        raise refused(CONSUMPTION, diagnostic(exc.reason_code)) from None
    if (descriptor["worker_image"], descriptor["profile_digest"]) != (activation["image"],
                                                                        activation["profile_sha256"]):
        raise refused(CONSUMPTION, "descriptor_identity")
    sha = descriptor_digest(descriptor)
    if plan["target_descriptor"]["revision"] != descriptor["revision"] \
            or plan["expected_descriptor"] != descriptor["predecessor"]:
        raise refused(CONSUMPTION, "plan_descriptor")
    intent = view["intent"]
    if intent["stage"] != ACTIVE:
        raise refused(CONSUMPTION, "delivery_not_active")
    if intent["plan_sha256"] != plan_sha256 or intent["target_id"] != target_id \
            or intent["descriptor_sha256"] != sha or canonical(intent["descriptor"]) != canonical(descriptor) \
            or intent["previous_descriptor_sha256"] != descriptor["predecessor"]:
        raise refused(CONSUMPTION, "delivery_binding")
    verdict = consumption_verdict(descriptor, receipt, expected_instance=intent["previous_instance_id"])
    if not verdict["consumed"]:
        raise refused(CONSUMPTION, verdict["reason_code"])
    instance = verdict["instance_id"]
    row = view["descriptor_row"]
    if not (row["consumed"] is True and row["rolled_back"] is False and row["descriptor_sha256"] == sha
            and canonical(row["descriptor"]) == canonical(descriptor) and row["plan_id"] == plan_id
            and row["instance_id"] == instance and row["observed_instance_id"] == instance
            and intent["instance_id"] == instance):
        raise refused(CONSUMPTION, "instance_binding")
    if view["open_plans"]:
        # An unexpected delivery in flight on this target invalidates what is observed here.
        raise refused(CONSUMPTION, "delivery_in_flight")
    try:
        lineage = validate_managed_lineage({"owner": "managed", "descriptor": descriptor, "instance_id": instance,
                                            "plan_id": plan_id})
    except MigrationRefused:
        raise refused(CONSUMPTION, "lineage_invalid") from None
    return {"target": target, "plan": plan, "plan_sha256": plan_sha256, "descriptor": descriptor,
            "descriptor_sha256": sha, "instance_id": instance, "lineage": lineage}


# ----- the owner canary (INV-OWNER-ACTIONS-001) ----------------------------------------------------------
def record_view(record) -> dict | None:
    """The `canary_record` projection: the accepted owner-canary action row's binding and outcome."""
    if not isinstance(record, dict):
        return None
    return {key: record.get(key) for key in RECORD_FIELDS}


def require_canary(consumed: dict, incumbent: dict, receipt, request, record, *, intent: dict,
                   started_at) -> None:
    """A passed owner canary explicitly bound to this plan, descriptor and instance.

    The incumbent `owner_qualified_canary` must pass first. It accepts a receipt with no instance and a
    truthy `passed`, so this producer also requires `passed is True`, a non-null exact instance and
    descriptor digest, and a receipt taken after this instance's startup. The receipt's evidence must
    be the completed owner action's own recorded outcome, and the delivery must have consumed with
    that same evidence. A recorded request must match the plan exactly. No new canary is issued and
    nothing is inferred from CI."""
    plan, lineage = consumed["plan"], consumed["lineage"]
    if plan["canary_check_id"] != CANARY_FLEET:
        raise refused(CANARY, "canary_check")
    if incumbent.get("passed") is not True:
        raise refused(CANARY, diagnostic(incumbent.get("reason_code") or "canary_owner_receipt_failed"))
    if not (isinstance(receipt, dict) and set(receipt) == CANARY_RECEIPT_FIELDS
            and receipt["schema"] == OWNER_CANARY_RECEIPT_SCHEMA):
        raise refused(CANARY, "canary_receipt_shape")
    if receipt["passed"] is not True:
        raise refused(CANARY, "canary_not_passed")
    if not (type(receipt["instance_id"]) is str and INSTANCE.fullmatch(receipt["instance_id"])):
        raise refused(CANARY, "canary_instance_missing")
    if receipt["instance_id"] != lineage["instance_id"]:
        raise refused(CANARY, "canary_instance")
    if receipt["descriptor_sha256"] != consumed["descriptor_sha256"]:
        raise refused(CANARY, "canary_descriptor")
    evidence = receipt["evidence"]
    if not (isinstance(evidence, dict) and evidence.get("plan_id") == lineage["plan_id"]
            and type(evidence.get("action_id")) is str and HEX64.fullmatch(evidence["action_id"])):
        raise refused(CANARY, "canary_evidence")
    recorded, started = usec_of(receipt["recorded_at"]), usec_of(started_at)
    if recorded is None or started is None or recorded + SKEW_USEC < started:
        raise refused(CANARY, "canary_before_startup")
    if request is not None and not canary_request_matches(request, consumed["target"], consumed["descriptor"], plan):
        raise refused(CANARY, "canary_request")
    if not isinstance(record, dict) or record.get("id") != evidence["action_id"]:
        raise refused(CANARY, "canary_record_missing")
    if record.get("kind") != DELIVERY_CANARY or record.get("state") != COMPLETED:
        raise refused(CANARY, "canary_record_state")
    binding = {"plan_id": lineage["plan_id"], "plan_sha256": consumed["plan_sha256"],
               "target_id": consumed["target"]["target_id"], "descriptor_sha256": consumed["descriptor_sha256"],
               "instance_id": lineage["instance_id"]}
    if record.get("binding") != binding or record.get("binding_sha256") != digest(binding):
        raise refused(CANARY, "canary_record_binding")
    outcome = record.get("outcome")
    if not (isinstance(outcome, dict) and outcome.get("state") == VERDICT_ACCEPTED
            and isinstance(outcome.get("evidence"), dict)):
        raise refused(CANARY, "canary_record_outcome")
    expected = {**outcome["evidence"], "action_id": record["id"], "plan_id": lineage["plan_id"]}
    if canonical(evidence) != canonical(expected) or receipt["reason_code"] != outcome.get("reason_code"):
        raise refused(CANARY, "canary_record_evidence")
    canary = intent.get("canary")
    if not (isinstance(canary, dict) and canary.get("passed") is True and canary.get("check_id") == CANARY_FLEET
            and canonical(canary.get("evidence")) == canonical(evidence)):
        raise refused(CANARY, "delivery_canary")


# ----- the observation document, its digest, receipts and draft ------------------------------------------
def _invalid(field: str) -> MigrationRefused:
    return MigrationRefused(INVALID, field)


def _text(value, pattern, field: str) -> str:
    if not (type(value) is str and pattern.fullmatch(value)):
        raise _invalid(field)
    return value


def validate_observation(document) -> dict:
    """Strict validation of the observation; returns the canonical copy. `ok` holds exactly when every
    check holds, every source is present, the activation and lineage are known and agree, and there
    is no reason code. A failure carries one producer refusal code."""
    if not isinstance(document, dict) or set(document) != set(OBSERVATION_FIELDS) \
            or document.get("schema") != OBSERVATION_SCHEMA:
        raise _invalid("observation")
    _text(document["migration_id"], TOKEN, "migration_id")
    if document["manifest_sha256"] is not None:
        _text(document["manifest_sha256"], HEX64, "manifest_sha256")
    start = usec_of(_text(document["observed_from"], UTC, "observed_from"))
    end = usec_of(_text(document["observed_to"], UTC, "observed_to"))
    if start is None or end is None or end < start:
        raise _invalid("observed_to")
    activation = document["activation"]
    if activation is not None:
        if not isinstance(activation, dict) or set(activation) != set(ACTIVATION_FIELDS):
            raise _invalid("activation")
        for key, pattern in (("id", HEX64), ("release_revision", COMMIT), ("image", IMAGE_DIGEST),
                             ("profile_sha256", HEX64), ("document_sha256", HEX64)):
            _text(activation[key], pattern, "activation." + key)
    lineage = document["lineage"]
    if lineage is not None:
        try:
            if validate_managed_lineage(lineage) != lineage:
                raise _invalid("lineage")
        except MigrationRefused:
            raise _invalid("lineage") from None
    checks = document["checks"]
    if not isinstance(checks, dict) or set(checks) != set(CHECKS) or any(type(v) is not bool for v in checks.values()):
        raise _invalid("checks")
    sources = document["sources"]
    if not isinstance(sources, dict) or set(sources) != set(SOURCES):
        raise _invalid("sources")
    for name, entry in sources.items():
        if entry is None:
            continue
        if not isinstance(entry, dict) or set(entry) != SOURCE_FIELDS:
            raise _invalid("sources." + name)
        _text(entry["sha256"], HEX64, "sources." + name + ".sha256")
        _text(entry["observed_at"], UTC, "sources." + name + ".observed_at")
    if type(document["ok"]) is not bool:
        raise _invalid("ok")
    if document["ok"]:
        if document["reason_code"] is not None or not all(checks.values()) \
                or any(entry is None for entry in sources.values()) \
                or None in (activation, lineage, document["manifest_sha256"]):
            raise _invalid("ok")
        descriptor = lineage["descriptor"]
        if (descriptor["worker_image"], descriptor["profile_digest"]) != (activation["image"],
                                                                            activation["profile_sha256"]):
            raise _invalid("lineage.descriptor")
    elif document["reason_code"] not in REFUSALS or all(checks.values()):
        raise _invalid("reason_code")
    return {key: document[key] for key in OBSERVATION_FIELDS}


def observation_digest(observation: dict) -> str:
    """The `result_sha256` of every receipt: the canonical JSON digest of the validated observation."""
    return digest(validate_observation(observation))


def observation_receipts(observation: dict, result_sha256: str, expected_id: str) -> dict:
    """The three existing evidence receipts, keyed by the `limited_active` gate they answer. They share
    one result digest; exit 0 and ok only on complete success. A failure keeps the subjects that are
    known and records exit 1, never a success."""
    ok, lineage = observation["ok"], observation["lineage"]
    code = 0 if ok else 1
    return {"host_activation": evidence_receipt("host-activation", expected_id, code, ok, result_sha256),
            "service_consumption": evidence_receipt(
                "service-startup", None if lineage is None else managed_consumption_subject(lineage), code, ok,
                result_sha256),
            "canary_admission": evidence_receipt(
                OBSERVATION, None if lineage is None else managed_canary_subject(lineage), code, ok, result_sha256)}


def transition_draft(observation: dict, evidence: dict, *, host: str, actor: str, config_sha256: str) -> dict:
    """The managed `restored_paused -> limited_active` transition the operator may submit: the current
    manifest and host configuration, the effective activation's identity, the three receipts and the
    canonical lineage. It is validated here and submitted by nothing in this producer."""
    if not observation["ok"]:
        raise _invalid("ok")
    activation = observation["activation"]
    return validate_transition({
        "schema": TRANSITION_SCHEMA, "migration_id": observation["migration_id"],
        "manifest_sha256": observation["manifest_sha256"], "from": RESTORED_PAUSED, "to": LIMITED_ACTIVE,
        "actor": actor, "host": host, "at": observation["observed_to"],
        "identity": {"config_sha256": config_sha256, "commit": activation["release_revision"],
                     "image": activation["image"], "profile_sha256": activation["profile_sha256"]},
        "evidence": {gate: [receipt] for gate, receipt in evidence.items()},
        "exit_code": 0, "reason_code": None, "lineage": observation["lineage"]})


__all__ = ["ACTIVATION_FIELDS", "CANARY", "CHANGED", "CHECKS", "CONSUMPTION", "DOCUMENT", "INVALID", "LAUNCH",
           "LAUNCH_ROLE", "MANAGED_MODULE", "MANAGED_UNIT", "OBSERVATION_FIELDS", "OBSERVATION_SCHEMA", "PROCESS",
           "REFUSALS", "SOURCES", "UNAVAILABLE", "UNIT_PROPERTIES", "delivery_view", "diagnostic", "launch_record",
           "migration_view", "observation_digest", "observation_receipts", "record_view", "require_activation_file",
           "require_canary", "require_consumption", "require_current", "require_entry", "require_head",
           "require_launch", "require_supervisor", "require_supervisor_launch", "source", "supervisor_launches", "transition_draft", "unit_facts", "usec_of",
           "utc_from_usec", "validate_observation"]
