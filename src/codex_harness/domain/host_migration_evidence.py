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

Every returned and archived source projection is built by `project`, the one record path (PH4-12). It
copies a source field by field through that source's explicit typed allowlist, on success and on
failure alike: a key outside the allowlist is never copied, not even its name, and a value that does
not have its declared type is null. An untrusted host document (the launcher file, the descriptor, the
startup receipt, the owner canary request and receipt) also keeps the digest of its raw bytes and fixed
`shape` facts, and its free-text path fields only once its own check accepted it. A rejected object
is never retained, and no source is redacted by name. The stable-capture recheck still compares the
raw identities, and each projection still commits to its raw input by a digest (`raw_sha256`; the
migration view through its own history, effective-head and manifest digests), so an `--expect`
comparison sees a change the sanitization drops.

A comparison (`--expect`, INV-HOST-MIGRATION-001 PH4-13) holds a fresh observation against an archived
one. Before the operator submits, every source digest, the activation and the lineage must be unchanged.
After the recorded managed transition (`post_transition`), the coordinator may have moved to
`limited_active` ONLY by that one transition: the last history entry is the archived draft's id and
lineage, and every other source is unchanged. A comparison emits no draft and no receipt.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from codex_harness.domain.host_delivery import (
    ACTIVE,
    CANARY_FLEET,
    CANARY_REQUEST_SCHEMA,
    DESCRIPTOR_SCHEMA,
    EVIDENCE_REF,
    INSTANCE,
    KIND_MANAGED_SYSTEMD,
    MANAGED_SYSTEMD_UNIT,
    MANAGED_TARGET_FIELDS,
    OWNER_CANARY_RECEIPT_SCHEMA,
    POST_MERGE_OPEN,
    RECEIPT_SCHEMA,
    REGISTRY_SCHEMA,
    TARGET_KINDS,
    TREE_ID,
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
from codex_harness.domain.host_delivery import IMAGE as DELIVERY_IMAGE
from codex_harness.domain.host_delivery import TOKEN as DELIVERY_TOKEN
from codex_harness.domain.host_migration import (
    ACTIVATION_SCHEMA,
    COMMIT,
    HEX64,
    HOST_ID,
    IMAGE_DIGEST,
    LIMITED_ACTIVE,
    MAX_TEXT,
    OBSERVATION,
    RESTORED_PAUSED,
    STATES,
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
    transition_id,
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
# A comparison's archived input that is not a complete, self-consistent success output of this producer.
EXPECT = "expect_invalid"
ARCHIVE_FIELDS = {"observation", "result_sha256", "projections", "evidence", "transition_draft"}
# The migration projection's fields a recorded transition legitimately changes; everything else in it
# (manifest, effective head, derived launcher document, configuration digest) must stay equal.
MIGRATION_PROGRESS = {"state", "transitions", "history_sha256", "previous_history_sha256", "last_transition"}
DIAGNOSTIC = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,79}$")

# The launcher's fixed `launch` event (deploy/aibox/zeus_aibox_service.py `launch`): emitted BEFORE the
# exec, and emitted by a dry run as well, so the event alone never proves a launch.
LAUNCH_EVENT_FIELDS = {"event", "role", "revision", "migration_id"}
# The journal fields `launch_record` reads (`journalctl --output-fields`); json output always adds
# `__CURSOR`, `__REALTIME_TIMESTAMP`, `__MONOTONIC_TIMESTAMP` and `_BOOT_ID`.
JOURNAL_FIELDS = ("MESSAGE", "_PID", "_STREAM_ID", "_SYSTEMD_UNIT", "_SYSTEMD_INVOCATION_ID", "_TRANSPORT")
# A journald cursor as `sd_journal_get_cursor` spells it: `s=<hex>;i=<hex>;b=<hex>;...`, lowercase hex only.
CURSOR = re.compile(r"^[a-z]=[0-9a-f]{1,64}(?:;[a-z]=[0-9a-f]{1,64}){0,7}$")
LAUNCH_ROLE = "managed-fleet"
MANAGED_UNIT = MANAGED_SYSTEMD_UNIT + ".service"
MANAGED_MODULE = "codex_harness.adapters.managed_runtime"
ENTRY_WORKLOAD = "fleet"
# A process start is known to one clock tick; systemd records ExecMainStartTimestamp right after its fork.
# Every `start_usec` below is CLOCK_MONOTONIC: `/proc` start ticks count CLOCK_BOOTTIME (suspend
# included), and the producer subtracts the boottime-monotonic offset it measured at observation time
# before comparing them with systemd's and journald's monotonic timestamps.
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
    launcher document derived from that head in `restored_paused`. `project` archives its typed copy."""
    try:
        manifest = validate_manifest(row["manifest"])
        exact = type(row["manifest_sha256"]) is str and manifest_digest(manifest) == row["manifest_sha256"]
        host = manifest["target"]["host_id"]
    except MigrationRefused:
        exact, host = False, None
    history = list(row.get("history") or [])
    view = {"migration_id": row["migration_id"], "state": row["state"], "manifest_sha256": row["manifest_sha256"],
            "manifest_exact": exact, "target_host_id": host, "transitions": len(history),
            "history_sha256": digest(history), "previous_history_sha256": digest(history[:-1]),
            "last_transition": history[-1] if history else None, "effective": None, "document": None}
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


def require_head(view: dict, migration_id: str, expected_id: str, *, post_transition: bool = False) -> dict:
    """Restored-paused, exact manifest, and the effective head is exactly the expected one. Returns the
    observation's `activation` block.

    A post-transition check (PH4-13) instead requires `limited_active` reached by a managed transition
    from `restored_paused` as the LAST history entry. Which transition and lineage that is, is the
    comparison's to decide against the archived draft; the launcher document stays the
    `restored_paused` derivation, because recording the transition never rewrites it."""
    if view["migration_id"] != migration_id:
        raise refused(DOCUMENT, "migration_id")
    if not view["manifest_exact"]:
        raise refused(DOCUMENT, "manifest")
    if view["state"] != (LIMITED_ACTIVE if post_transition else RESTORED_PAUSED):
        raise refused(DOCUMENT, "migration_state")
    if post_transition:
        last = view["last_transition"]
        if not (isinstance(last, dict) and last.get("from") == RESTORED_PAUSED and last.get("to") == LIMITED_ACTIVE
                and isinstance(last.get("lineage"), dict)):
            raise refused(DOCUMENT, "transition_last")
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
    """The ONE launcher document on the main pid's journal streams in this invocation.

    journald stores each line of the launcher's indented JSON as one entry, so the document is
    reassembled per stream (`_STREAM_ID`) from a line that is exactly `{` to one that is exactly `}`.

    journald attributes EVERY line of a stdout/stderr stream to the pid that opened the stream. systemd
    connects the unit's streams from the forked main process before any exec, so the launcher's lines
    before its exec, the exec'd supervisor's lines, and the lines of any descendant that inherited the
    descriptor all carry the main pid. `_PID` therefore does not say which program wrote a line; it
    only binds the lines to this unit's main process. The launch is proven apart from the journal:
    the main process must be the exec'd supervisor with the exact argv, started in this invocation's
    fork window (`require_supervisor`), and the event must follow that start (`require_launch`). A
    dry run never execs, so its main process is not the supervisor. A second launch document on the
    stream, from a dry run or a descendant, is ambiguous and refuses. A `launch_refused` event, or a
    line from another boot, invocation, unit or transport refuses. A main-pid document that does not
    parse, or does not end, is unknown: it is never skipped."""
    pid, open_documents, documents = str(main_pid), {}, []
    for entry in entries:
        if not isinstance(entry, dict):
            raise refused(UNAVAILABLE, "journal_entry")
        if entry.get("_PID") != pid:
            continue
        message, stream = entry.get("MESSAGE"), entry.get("_STREAM_ID")
        if type(message) is not str:
            if stream in open_documents:
                raise refused(UNAVAILABLE, "journal_entry")
            continue
        if stream not in open_documents:
            if message == "{":
                open_documents[stream] = [entry]
            elif message.startswith("{") and message.endswith("}"):
                documents.append([entry])
            continue
        open_documents[stream].append(entry)
        if message == "}":
            documents.append(open_documents.pop(stream))
    if open_documents:
        raise refused(UNAVAILABLE, "journal_entry")
    parsed = []
    for lines in documents:
        try:
            document = json.loads("\n".join(line["MESSAGE"] for line in lines))
        except ValueError:
            raise refused(UNAVAILABLE, "journal_entry") from None
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
    if not (type(cursor) is str and len(cursor) <= 400 and CURSOR.fullmatch(cursor)):
        raise refused(UNAVAILABLE, "journal_entry")
    realtime = _journal_number(first, "__REALTIME_TIMESTAMP")
    return {"unit": unit, "boot_id": boot_id, "invocation_id": invocation_id, "pid": main_pid, "cursor": cursor,
            "monotonic_usec": _journal_number(first, "__MONOTONIC_TIMESTAMP"), "realtime_usec": realtime,
            "at": utc_from_usec(realtime), "lines": len(lines), "event": document}


def require_launch(record: dict, unit: dict, supervisor: dict, *, migration_id: str, revision: str) -> None:
    """A real launch of THIS activation that happened inside THIS invocation's main process: the fixed
    event fields, then its time after the unit's exec-main start and after that process began (both
    CLOCK_MONOTONIC)."""
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


def require_supervisor(unit: dict, supervisor: dict, *, argv_sha256: str) -> None:
    """The unit's main process is the supervisor the launcher exec'd: running unit, main pid, its
    cgroup, direct child of the service manager, the exact supervise argv of the activation release
    (compared by digest: the raw argv of a process is never kept), and a monotonic start inside the
    fork window of the unit's exec-main start (a reused pid starts later)."""
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
    if supervisor["argv_sha256"] != argv_sha256:
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


def supervisor_facts(revision: str) -> dict:
    """What a supervisor that passed `require_supervisor` is: the only argv facts ever archived."""
    return {"command": "supervise", "module": MANAGED_MODULE, "revision": revision}


def entry_facts() -> dict:
    """What an entry that passed `require_entry` is: the registered interpreter's managed entry of the
    real Fleet workload. The interpreter is named by its binding, never by its path or argv."""
    return {"command": "entry", "module": MANAGED_MODULE, "workload": ENTRY_WORKLOAD, "interpreter": "registered"}


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


def require_entry(entry: dict, supervisor: dict, unit: dict, launch: dict, *, argv_sha256: str, started_at) -> None:
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
    if entry["argv_sha256"] != argv_sha256:
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
    """The delivery rows' binding fields the checks below read and the recheck compares; `project`
    archives their typed copy."""
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
    """The owner-canary action row's binding and outcome as the recheck compares them; `project`
    archives their typed copy."""
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


# ----- the sanitized source projections: the one record path (PH4-12) -----------------------------------
PATH = re.compile(r"^/[A-Za-z0-9._@+~,/-]{0,%d}$" % (MAX_TEXT - 1))


class _Nullable:
    """A field whose value may be JSON null."""

    def __init__(self, kind):
        self.kind = kind


class _Free:
    """A free-text field of an untrusted host document: kept only once that document's own check
    accepted it (then it is bound to the owner-registered value), withheld as null before."""

    def __init__(self, kind):
        self.kind = kind


class _List:
    def __init__(self, kind):
        self.kind = kind


def _path_text(value) -> str:
    """An absolute path as the registry, the descriptor and the startup receipt spell it: bounded, of
    path characters only (no space, `=` or control character), without a parent step."""
    if not (type(value) is str and PATH.fullmatch(value) and ".." not in value.split("/")):
        raise ValueError("path")
    return value


HEX32 = INSTANCE
CODE = DIAGNOSTIC
# A cgroup path as the kernel and systemd print it (systemd escapes as `\x2d`).
CGROUP = re.compile(r"^/[A-Za-z0-9._@:+\\/-]{0,399}$")
CURRENT = re.compile(r"^(?:[0-9a-f]{40}|foreign)$")
# The untrusted host documents and the journal's launch event, field by field.
ACTIVATION_DOCUMENT = {"schema": frozenset({ACTIVATION_SCHEMA}), "migration_id": TOKEN, "host_id": HOST_ID,
                       "state": frozenset(STATES), "release_revision": COMMIT, "intent_id": HEX64,
                       "manifest_sha256": HEX64, "supersedes": HEX64, "activation_kind": frozenset({"successor"})}
DESCRIPTOR_DOCUMENT = {"schema": frozenset({DESCRIPTOR_SCHEMA}), "target_id": DELIVERY_TOKEN,
                       "root": _Free(_path_text), "revision": COMMIT, "worker_image": DELIVERY_IMAGE,
                       "profile_digest": HEX64, "predecessor": _Nullable(HEX64)}
STARTUP_DOCUMENT = {"schema": frozenset({RECEIPT_SCHEMA}), "target_id": DELIVERY_TOKEN, "instance_id": HEX32,
                    "pid": int, "started_at": UTC, "runtime_root": _Free(_path_text),
                    "module_root": _Free(_path_text), "descriptor_sha256": HEX64, "revision": COMMIT,
                    "worker_image": DELIVERY_IMAGE, "profile_digest": HEX64}
# The owner canary's evidence: the action and plan, then the accepted (or rejected) outcome's own facts.
CANARY_EVIDENCE = {"action_id": HEX64, "plan_id": DELIVERY_TOKEN, "job_id": DELIVERY_TOKEN,
                   "operation_id": DELIVERY_TOKEN, "decision_id": DELIVERY_TOKEN, "execution_ref": EVIDENCE_REF}
CANARY_RECEIPT_DOCUMENT = {"schema": frozenset({OWNER_CANARY_RECEIPT_SCHEMA}),
                           "descriptor_sha256": _Nullable(HEX64), "instance_id": _Nullable(HEX32), "passed": bool,
                           "evidence": _Nullable(CANARY_EVIDENCE), "reason_code": _Nullable(CODE),
                           "recorded_at": UTC}
CANARY_REQUEST_DOCUMENT = {"schema": frozenset({CANARY_REQUEST_SCHEMA}), "action_id": HEX64,
                           "plan_id": DELIVERY_TOKEN, "plan_sha256": HEX64, "target_id": DELIVERY_TOKEN,
                           "revision": COMMIT, "expected_descriptor": _Nullable(HEX64), "requested_at": UTC}
LAUNCH_EVENT = {"event": CODE, "role": CODE, "revision": COMMIT, "migration_id": TOKEN}
# The coordinator record: the view `migration_view` derives, and the last history entry of any kind.
EFFECTIVE_VIEW = {"id": HEX64, "kind": frozenset({"intent", "successor"}), "host_id": HOST_ID,
                  "release_revision": COMMIT, "image": IMAGE_DIGEST, "profile_sha256": HEX64,
                  "predecessor_id": _Nullable(HEX64)}
HISTORY_ENTRY = {"id": HEX64, "event": CODE, "from": frozenset(STATES), "to": frozenset(STATES), "at": UTC,
                 "actor": TOKEN, "host": TOKEN, "reason_code": _Nullable(TOKEN), "intent_id": HEX64,
                 "successor_id": HEX64, "predecessor_id": HEX64, "release_revision": COMMIT,
                 "lineage": validate_managed_lineage}
MIGRATION_SOURCE = {"migration_id": TOKEN, "state": frozenset(STATES), "manifest_sha256": HEX64,
                    "manifest_exact": bool, "target_host_id": _Nullable(TOKEN), "transitions": int,
                    "history_sha256": HEX64, "previous_history_sha256": HEX64,
                    "last_transition": _Nullable(HISTORY_ENTRY), "effective": _Nullable(EFFECTIVE_VIEW),
                    "document": _Nullable(ACTIVATION_DOCUMENT), "config_sha256": _Nullable(HEX64)}
ACTIVATION_FILE_FACTS = {"fence": bool, "current": _Nullable(CURRENT), "release_present": bool}
# The unit, the journal's launch record and the two processes.
UNIT_SOURCE = {"active_state": CODE, "sub_state": CODE, "main_pid": int, "exec_main_pid": int,
               "invocation_id": HEX32, "control_group": CGROUP, "exec_main_start_usec": int}
SUPERVISOR_LINE = {"event": CODE, "at": UTC, "invocation_id": _Nullable(HEX32), "descriptor_sha256": HEX64,
                   "workload": CODE, "reason_code": CODE}
VALIDATED_FACTS = {"command": CODE, "module": CODE, "revision": COMMIT, "workload": CODE, "interpreter": CODE}
PROCESS_SOURCE = {"pid": int, "state": frozenset({"absent", "present", "replaced"}), "start_ticks": int,
                  "boottime_offset_ticks": int, "start_usec": int, "tick_usec": int, "ppid": int,
                  "cgroup": _Nullable(CGROUP), "argv_sha256": _Nullable(HEX64),
                  "role": frozenset({"supervisor", "entry"}), "argv_match": bool,
                  "validated": _Nullable(VALIDATED_FACTS), "boot_id": HEX32, "invocation_id": HEX32,
                  "unit": UNIT_SOURCE, "launches": _List(SUPERVISOR_LINE)}
LAUNCH_SOURCE = {"unit": CODE, "boot_id": HEX32, "invocation_id": HEX32, "pid": int, "cursor": CURSOR,
                 "monotonic_usec": int, "realtime_usec": int, "at": UTC, "lines": int, "event": LAUNCH_EVENT}
SEALED_RUNTIME = {"revision": COMMIT, "tree": TREE_ID, "files": int, "environment_lock": _Nullable(HEX64),
                  "manifest_sha256": HEX64}
# The delivery rows and the owner-action record, with their nested canary outcome and evidence.
TARGET_ROW = {"target_id": DELIVERY_TOKEN, "kind": frozenset(TARGET_KINDS), "root": _path_text,
              "state_dir": _path_text, "service": DELIVERY_TOKEN, "source": _path_text, "python": _path_text,
              "environment_lock": _Nullable(HEX64)}
INTENT_CANARY = {"passed": bool, "pending": bool, "evidence": _Nullable(CANARY_EVIDENCE),
                 "reason_code": _Nullable(CODE), "check_id": CODE}
ROLLBACK = {"requested": bool, "restored": bool, "verified": bool, "reason_code": _Nullable(CODE)}
INTENT_ROW = {"plan_id": DELIVERY_TOKEN, "target_id": DELIVERY_TOKEN, "plan_sha256": HEX64, "stage": CODE,
              "revision": COMMIT, "descriptor": _Nullable(DESCRIPTOR_DOCUMENT), "descriptor_sha256": _Nullable(HEX64),
              "previous_descriptor_sha256": _Nullable(HEX64), "previous_instance_id": _Nullable(HEX32),
              "instance_id": _Nullable(HEX32), "candidate_instance_id": _Nullable(HEX32),
              "canary": _Nullable(INTENT_CANARY), "rollback": _Nullable(ROLLBACK), "updated_at": UTC}
DESCRIPTOR_ROW = {"target_id": DELIVERY_TOKEN, "descriptor": _Nullable(DESCRIPTOR_DOCUMENT),
                  "descriptor_sha256": _Nullable(HEX64), "consumed": bool, "startup_observed": bool,
                  "observed_instance_id": _Nullable(HEX32), "observed_revision": _Nullable(COMMIT),
                  "instance_id": _Nullable(HEX32), "plan_id": _Nullable(DELIVERY_TOKEN),
                  "release_id": _Nullable(DELIVERY_TOKEN), "rolled_back": bool, "updated_at": UTC}
DELIVERY_SOURCE = {"target": TARGET_ROW,
                   "plan": {"plan_id": DELIVERY_TOKEN, "plan_sha256": HEX64, "plan": validate_plan},
                   "intent": INTENT_ROW, "descriptor_row": DESCRIPTOR_ROW, "open_plans": _List(DELIVERY_TOKEN)}
CANARY_BINDING = {"plan_id": DELIVERY_TOKEN, "plan_sha256": HEX64, "target_id": DELIVERY_TOKEN,
                  "descriptor_sha256": HEX64, "instance_id": HEX32}
RECORD_SOURCE = {"id": HEX64, "kind": CODE, "state": CODE, "reason_code": _Nullable(CODE),
                 "binding": CANARY_BINDING, "binding_sha256": HEX64,
                 "outcome": _Nullable({"state": CODE, "reason_code": _Nullable(CODE),
                                       "evidence": _Nullable(CANARY_EVIDENCE)}),
                 "version": int, "updated_at": UTC}


def _typed(value, kind, free: bool = True) -> tuple:
    """`(projection, typed)`: the value when it has the declared type, else None; an object keeps only
    its allowlisted keys, each projected by its own kind. `typed` says whether nothing was dropped."""
    if isinstance(kind, _Nullable):
        return (None, True) if value is None else _typed(value, kind.kind, free)
    if isinstance(kind, _Free):
        projection, typed = _typed(value, kind.kind, free)
        return (projection if free else None), typed
    if isinstance(kind, dict):
        if not isinstance(value, dict):
            return None, False
        fields = {key: _typed(value[key], sub, free) for key, sub in kind.items() if key in value}
        return ({key: projection for key, (projection, _) in fields.items()},
                set(value) <= set(kind) and all(typed for _, typed in fields.values()))
    if isinstance(kind, _List):
        if not isinstance(value, list):
            return None, False
        items = [_typed(item, kind.kind, free) for item in value]
        return [projection for projection, _ in items], all(typed for _, typed in items)
    if isinstance(kind, re.Pattern):
        typed = type(value) is str and kind.fullmatch(value) is not None
    elif isinstance(kind, frozenset):
        typed = type(value) is str and value in kind
    elif kind is int or kind is bool:
        typed = type(value) is kind
    else:
        # The existing strict validator of that document: its canonical copy, or nothing of it.
        try:
            return kind(value), True
        except Exception:  # noqa: BLE001 - any refusal keeps nothing of the value
            return None, False
    return (value if typed else None), typed


def _json_type(value) -> str:
    for kinds, name in ((dict, "object"), (list, "array"), (str, "string"), (bool, "boolean"),
                        ((int, float), "number")):
        if isinstance(value, kinds):
            return name
    return "null"


def _shape(document, allowlist: dict) -> dict:
    """Fixed facts about an untrusted document against its allowlist: its JSON type, the allowlisted
    names missing or not of their type, and how many keys lie outside it (never their names)."""
    if not isinstance(document, dict):
        return {"type": _json_type(document), "missing": sorted(allowlist), "invalid": [], "extra": 0}
    return {"type": "object", "missing": sorted(key for key in allowlist if key not in document),
            "invalid": sorted(key for key, kind in allowlist.items()
                              if key in document and not _typed(document[key], kind)[1]),
            "extra": sum(1 for key in document if key not in allowlist)}


def _host_document(raw_sha256, document, allowlist: dict, accepted: bool) -> dict:
    """An untrusted host document: the digest of its raw bytes, whether its check accepted it, its
    allowlisted typed fields (its free-text fields only when accepted) and its fixed shape."""
    return {"raw_sha256": _typed(raw_sha256, HEX64)[0], "accepted": accepted is True,
            "document": _typed(document, allowlist, accepted is True)[0], "shape": _shape(document, allowlist)}


def _with_raw(facts, allowlist: dict) -> dict:
    """A typed projection that commits to its whole raw input by digest, so an archive comparison
    still sees any change the sanitization drops."""
    return {**(_typed(facts, allowlist)[0] or {}), "raw_sha256": digest(facts)}


def _canary_source(facts: dict, accepted: bool) -> dict:
    return {name: None if facts[name + "_sha256"] is None else
            _host_document(facts[name + "_sha256"], facts[name], allowlist, accepted)
            for name, allowlist in (("receipt", CANARY_RECEIPT_DOCUMENT), ("request", CANARY_REQUEST_DOCUMENT))}


_PROJECTIONS = {
    # The coordinator view commits to its raw row through its own digests: the exact manifest, the
    # history (whole and previous), the effective head's id and the configuration.
    "migration": lambda facts, accepted: _typed(facts, MIGRATION_SOURCE)[0],
    "activation_file": lambda facts, accepted: {
        **_typed(facts, ACTIVATION_FILE_FACTS)[0],
        **_host_document(facts["raw_sha256"], facts["document"], ACTIVATION_DOCUMENT, accepted)},
    "launch": lambda facts, accepted: {**_with_raw(facts, LAUNCH_SOURCE),
                                       "event_shape": _shape(facts.get("event"), LAUNCH_EVENT)},
    "supervisor": lambda facts, accepted: _with_raw(facts, PROCESS_SOURCE),
    "entry": lambda facts, accepted: _with_raw(facts, PROCESS_SOURCE),
    "descriptor": lambda facts, accepted: {
        **_host_document(facts["raw_sha256"], facts["document"], DESCRIPTOR_DOCUMENT, accepted),
        "runtime": _typed(facts["runtime"], _Nullable(SEALED_RUNTIME))[0]},
    "startup": lambda facts, accepted: _host_document(facts["raw_sha256"], facts["document"], STARTUP_DOCUMENT,
                                                      accepted),
    "delivery": lambda facts, accepted: _with_raw(facts, DELIVERY_SOURCE),
    "canary_receipt": _canary_source,
    "canary_record": lambda facts, accepted: _with_raw(record_view(facts), RECORD_SOURCE),
}


def project(name: str, facts, *, accepted: bool = False) -> dict:
    """The sanitized projection of one source, exactly as it is returned, archived and hashed into
    `sources` (INV-HOST-MIGRATION-001 PH4-12). `facts` is what the producer read; nothing of it passes
    except through the source's typed allowlist. `accepted` says the source's own check accepted it."""
    return _PROJECTIONS[name](facts, accepted)


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


# ----- the comparison against an archived observation (PH4-13) ------------------------------------------
def _expect(field: str) -> MigrationRefused:
    return MigrationRefused(EXPECT, field)


def validate_archive(document, *, migration_id: str, expected_id: str, target_id: str, plan_id: str) -> dict:
    """The archived success output an operator compares against, refused before anything is read.

    It must be this producer's own complete success: a valid `ok` observation whose canonical digest is
    the archived `result_sha256`, every archived projection hashing to its source, the three receipts
    recomputed from that observation, and a valid managed transition draft carrying exactly those
    receipts, lineage, manifest, activation identity and the configuration digest the `migration`
    projection committed. It must be for this migration, effective activation, target and plan. A
    comparison output (no draft, no receipts) is never an archive. Content that cannot even be
    canonicalized is the same fixed refusal, with no exception text."""
    try:
        return _validate_archive(document, migration_id=migration_id, expected_id=expected_id,
                                 target_id=target_id, plan_id=plan_id)
    except MigrationRefused:
        raise
    except Exception:  # noqa: BLE001 - e.g. a lone surrogate that canonical JSON cannot encode
        pass
    raise _expect("archive")


def _validate_archive(document, *, migration_id: str, expected_id: str, target_id: str, plan_id: str) -> dict:
    if not isinstance(document, dict) or not ARCHIVE_FIELDS <= set(document):
        raise _expect("archive")
    try:
        observation = validate_observation(document["observation"])
    except MigrationRefused:
        raise _expect("observation") from None
    if canonical(observation) != canonical(document["observation"]) or observation["ok"] is not True:
        raise _expect("observation")
    result_sha256 = digest(observation)
    if document["result_sha256"] != result_sha256:
        raise _expect("result_sha256")
    projections = document["projections"]
    if not (isinstance(projections, dict) and set(projections) == set(SOURCES)
            and all(digest(projections[name]) == observation["sources"][name]["sha256"] for name in SOURCES)):
        raise _expect("projections")
    migration = projections["migration"]
    if not (isinstance(migration, dict) and MIGRATION_PROGRESS <= set(migration) and "config_sha256" in migration
            and type(migration["transitions"]) is int and type(migration["history_sha256"]) is str):
        raise _expect("projections")
    activation, lineage = observation["activation"], observation["lineage"]
    if observation["migration_id"] != migration_id:
        raise _expect("migration_id")
    if activation["id"] != expected_id:
        raise _expect("expected_id")
    if lineage["plan_id"] != plan_id or lineage["descriptor"]["target_id"] != target_id:
        raise _expect("lineage")
    receipts = observation_receipts(observation, result_sha256, expected_id)
    if canonical(document["evidence"]) != canonical(receipts):
        raise _expect("evidence")
    try:
        draft = validate_transition(document["transition_draft"])
    except MigrationRefused:
        raise _expect("transition_draft") from None
    identity = {"config_sha256": migration["config_sha256"], "commit": activation["release_revision"],
                "image": activation["image"], "profile_sha256": activation["profile_sha256"]}
    if canonical(draft) != canonical(document["transition_draft"]) or draft["migration_id"] != migration_id \
            or (draft["from"], draft["to"]) != (RESTORED_PAUSED, LIMITED_ACTIVE) \
            or draft["manifest_sha256"] != observation["manifest_sha256"] \
            or canonical(draft.get("lineage")) != canonical(lineage) or canonical(draft["identity"]) != canonical(identity) \
            or canonical(draft["evidence"]) != canonical({gate: [receipt] for gate, receipt in receipts.items()}):
        raise _expect("transition_draft")
    return {"observation": observation, "result_sha256": result_sha256, "projections": projections,
            "transition_id": transition_id(draft)}


def compare_observation(archive: dict, observation: dict, projections: dict, *, post_transition: bool,
                        refusal: tuple = (None, None)) -> dict:
    """The `comparison` wrapper entry: the fresh observation held against the validated archive.

    A fresh observation that failed cannot be compared: its own fixed code is the comparison's. Then
    the manifest, the activation, the lineage and every non-migration source digest must be unchanged
    (`activation_observation_changed` names the first difference). Before submission the `migration`
    source must be unchanged too. After the transition (`post_transition`) the migration may differ
    ONLY by one appended history entry: the transition whose id is the archived draft's, whose lineage
    is both the archived and the fresh one; manifest, head, launcher document and configuration
    digest stay equal. `post_check` is `ok` only then. Nothing here is a receipt or a draft."""
    mode = "post_transition" if post_transition else "pre_submit"

    def verdict(code, detail) -> dict:
        return {"mode": mode, "expected_result_sha256": archive["result_sha256"], "ok": code is None,
                "reason_code": code, "detail": None if detail is None else diagnostic(detail),
                "post_check": "ok" if post_transition and code is None else None}

    if not observation["ok"]:
        return verdict(observation["reason_code"], refusal[1] or "observation")
    expected = archive["observation"]
    for key in ("migration_id", "manifest_sha256", "activation", "lineage"):
        if canonical(observation[key]) != canonical(expected[key]):
            return verdict(CHANGED, key)
    for name in SOURCES:
        if name != "migration" and observation["sources"][name]["sha256"] != expected["sources"][name]["sha256"]:
            return verdict(CHANGED, name)
    if not post_transition:
        if observation["sources"]["migration"]["sha256"] != expected["sources"]["migration"]["sha256"]:
            return verdict(CHANGED, "migration")
        return verdict(None, None)
    before, after = archive["projections"]["migration"], projections["migration"]

    def stable(view: dict) -> dict:
        return {key: value for key, value in view.items() if key not in MIGRATION_PROGRESS}

    if canonical(stable(after)) != canonical(stable(before)):
        return verdict(CHANGED, "migration")
    if after["transitions"] != before["transitions"] + 1 or after["previous_history_sha256"] != before["history_sha256"]:
        return verdict(CHANGED, "transition_history")
    last = after["last_transition"]
    if last.get("id") != archive["transition_id"]:
        return verdict(CHANGED, "transition_id")
    if canonical(last.get("lineage")) != canonical(expected["lineage"]) \
            or canonical(last.get("lineage")) != canonical(observation["lineage"]):
        return verdict(CHANGED, "transition_lineage")
    return verdict(None, None)


__all__ = ["ACTIVATION_FIELDS", "CANARY", "CHANGED", "CHECKS", "CONSUMPTION", "DOCUMENT", "EXPECT", "INVALID",
           "JOURNAL_FIELDS", "LAUNCH", "LAUNCH_ROLE", "MANAGED_MODULE", "MANAGED_UNIT", "OBSERVATION_FIELDS",
           "OBSERVATION_SCHEMA", "PROCESS", "REFUSALS", "SOURCES", "UNAVAILABLE", "UNIT_PROPERTIES",
           "compare_observation", "delivery_view", "diagnostic", "entry_facts", "launch_record", "migration_view",
           "observation_digest", "observation_receipts", "project", "record_view", "require_activation_file",
           "require_canary", "require_consumption", "require_current", "require_entry", "require_head",
           "require_launch", "require_supervisor", "require_supervisor_launch", "source", "supervisor_facts",
           "supervisor_launches", "transition_draft", "unit_facts", "usec_of", "utc_from_usec", "validate_archive",
           "validate_observation"]
