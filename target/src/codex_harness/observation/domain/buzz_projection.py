"""Buzz projection (domain): pinned ids, the unsigned event builders, thread tags, bounds, coalescing, interventions.

Layer: domain
Context: observation
Owns: `NS_ZEUS_BUZZ` with `task_artifact_d` / `desk_session_id` (UUIDv5), the schema URNs and `supported`,
    the UNSIGNED builders `task_root`, `task_card`, `org_snapshot` and `receipt` (kind 9 / 45010 dicts for the signer),
    the NIP-10 tag sets (`thread_post_tags`, `receipt_tags`, `resolve_thread`), the bounds, `may_publish` (coalescing)
    and `interventions` (button availability)
Does not own: signing (credentials custody; Batch A's `NostrEventSigner`), publishing, the outbox, the bindings and
    heads, reading Zeus read models (B4 `BuzzProjection`), the command envelope (coordination `remote_control`)
Entry points: NS_ZEUS_BUZZ, task_artifact_d, desk_session_id, task_root, task_card, org_snapshot, receipt,
    thread_post_tags, receipt_tags, resolve_thread, may_publish, interventions, supported, evidence_ref_ok
Contracts: Buzz DESIGN §4.1-§4.5 (schemas, thread conventions), §6.1.4 (zr-op logical identity), §6.3 (coalescing)
    in aibox-migration-001/evidence/buzz-zeus-localization-001/DESIGN.md; batch-b/RESEARCH-B QB1 (NIP-10 thread
    tags as Buzz resolves them: a lone `root` never threads), QB2 (`h` on every kind 9), QB3 (UUIDv5, RFC 9562);
    NIP-10, NIP-29

Pure: every builder returns `{"kind", "created_at", "tags", "content"}` with a deterministic tag order and canonical
JSON (sorted keys, UTF-8). Where §4 is silent the stricter reading is taken (marked "REFUSE-READING").
"""

from __future__ import annotations

import json
import re
import uuid

from codex_harness.coordination.domain import remote_control as rc
from codex_harness.kernel.errors import ContractError

# One pinned namespace, generated once with uuid.uuid4() on 2026-10-01; it never changes (RESEARCH-B QB3). The
# Desktop recomputes `d` and the desk session id from this value and the UTF-8 name.
NS_ZEUS_BUZZ = uuid.UUID("749812e0-6b7f-48d6-b33a-aadbee8eb990")

KIND_POST = 9
KIND_ARTIFACT = 45010

ORG_SCHEMA = "urn:zeus:buzz-org:1"
TASK_ROOT_SCHEMA = "urn:zeus:buzz-task-root:1"
TASK_SCHEMA = "urn:zeus:buzz-task:1"
RECEIPT_SCHEMA = "urn:zeus:buzz-receipt:1"
COMMAND_SCHEMA = rc.COMMAND_SCHEMA_PREFIX + str(rc.COMMAND_MAJOR)
KNOWN_MAJORS = {"org": 1, "task-root": 1, "task": 1, "receipt": 1, "command": rc.COMMAND_MAJOR}

MAX_SUMMARY_CHARS = 2000  # §4.5
MAX_REASON_CHARS = rc.MAX_REASON_CHARS  # §4.3 (500)
ORG_TITLE = "Zeus organization"  # NIP-AR: every non-delete revision needs a `title`; the org snapshot's is fixed
MAX_TITLE_CHARS = 500  # REFUSE-READING: the title tag/field has no §4 bound; a declared one
MAX_EVIDENCE_REFS = 100  # REFUSE-READING: §4.5 gives no count; a declared bound
MAX_EVIDENCE_REF_CHARS = 128
MAX_CONTENT_BYTES = 262144  # the declared maximum; every artifact stays STRICTLY below it (§4.5: far below)

ORG_MIN_PERIOD = 10  # §6.3: seconds between org revisions
TASK_MIN_PERIOD = 2  # §6.3: seconds between task revisions
DESK_MIGRATED = False  # DESIGN-B §1: desk ops are refused `desk_not_migrated` until S8 moves FrontDesk

CARD_OPS = ("create", "update")
ORG_STATES = ("idle", "busy", "paused", "unknown")

_SCHEMA_URN = re.compile(r"urn:zeus:buzz-(org|task-root|task|receipt|command):(0|[1-9][0-9]*)")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_EVIDENCE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]*")
_DRIVE = re.compile(r"[A-Za-z]:")
_CARD_KEYS = frozenset({"task_id", "version", "generation", "status", "assignee", "sender", "team", "stage",
                        "updated_at", "observed_at", "summary", "evidence_refs", "interventions"})
_ORG_KEYS = frozenset({"version", "generated_at", "roles", "fleet"})
_ROLE_KEYS = frozenset({"id", "role", "parent", "team", "display", "pubkey", "status"})
_ROLE_STATUS_KEYS = frozenset({"state", "task_id", "last_activity_at", "observed_at"})
_FLEET_KEYS = frozenset({"paused", "version", "activation_hold"})
_WORK_KEYS = frozenset({"state", "result", "evidence_at"})


# --- ids -------------------------------------------------------------------------------------------------------

def task_artifact_d(task_id: str) -> str:
    """The 45010 `d` of a task card: `uuid5(NS_ZEUS_BUZZ, "zeus.task:" + task_id)` (§4.5, RESEARCH-B QB3)."""
    _text(task_id, "task_id")
    return str(uuid.uuid5(NS_ZEUS_BUZZ, "zeus.task:" + task_id))


def desk_session_id(owner_pubkey_hex: str) -> str:
    """The owner's default desk session: `uuid5(NS_ZEUS_BUZZ, "zeus-desk:" + owner_pubkey_hex)` (§4.3)."""
    _hex64(owner_pubkey_hex, "owner_pubkey_hex")
    return str(uuid.uuid5(NS_ZEUS_BUZZ, "zeus-desk:" + owner_pubkey_hex))


def supported(schema: object) -> bool:
    """True iff `schema` is a known Zeus Buzz schema URN at its known MAJOR (an unknown major is refused, §4)."""
    match = _SCHEMA_URN.fullmatch(schema) if isinstance(schema, str) else None
    return match is not None and KNOWN_MAJORS[match.group(1)] == int(match.group(2))


# --- validation helpers ------------------------------------------------------------------------------------------

def _text(value: object, name: str, *, limit: int | None = None, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty) or (limit is not None and len(value) > limit):
        raise ContractError(f"buzz projection: {name} must be a string"
                            + (f" of at most {limit} characters" if limit is not None else ""))
    return value


def _opt_text(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"buzz projection: {name} must be a non-negative integer")
    return value


def _opt_int(value: object, name: str) -> int | None:
    return None if value is None else _int(value, name)


def _opt_bool(value: object, name: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ContractError(f"buzz projection: {name} must be a boolean or null")
    return value


def _hex64(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ContractError(f"buzz projection: {name} must be 64 lowercase hex characters")
    return value


def _exact(value: object, keys: frozenset, name: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ContractError(f"buzz projection: {name} must have exactly the keys {sorted(keys)}")
    return value


def evidence_ref_ok(ref: object) -> bool:
    """An evidence ref is an OPAQUE id (§4.5): never a path, URL or relative traversal (REFUSE-READING)."""
    return (isinstance(ref, str) and len(ref) <= MAX_EVIDENCE_REF_CHARS and _EVIDENCE_REF.fullmatch(ref) is not None
            and ".." not in ref and _DRIVE.match(ref) is None and "://" not in ref)


def _canonical(obj: object) -> str:
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractError("buzz projection: content is not canonical JSON") from exc


def _bounded(content: str) -> str:
    try:
        size = len(content.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ContractError("buzz projection: content is not valid Unicode") from exc
    if size >= MAX_CONTENT_BYTES:
        raise ContractError("buzz projection: content reaches the declared 256 KiB bound")
    return content


def _fence(name: str, obj: dict) -> str:
    return _bounded(f"```{name}\n{_canonical(obj)}\n```")


def _event(kind: int, created_at: int, tags: list, content: str) -> dict:
    return {"kind": kind, "created_at": _int(created_at, "created_at"), "tags": tags, "content": content}


# --- thread tags (RESEARCH-B QB1/QB2) -----------------------------------------------------------------------------

def thread_post_tags(channel: str, root_event_id: str, replied_author: str) -> list:
    """Tags of an in-thread kind 9: `e root "" reply` (a lone `root` never threads in Buzz), `p`, `h`."""
    return [["e", _hex64(root_event_id, "root_event_id"), "", "reply"], ["p", _hex64(replied_author, "replied_author")],
            ["h", _text(channel, "channel")]]


def receipt_tags(channel: str, root_event_id: str, command_event_id: str, command_author: str, command_id: str,
                 revision: int) -> list:
    """Tags of a receipt: `e root "" root` AND `e command "" reply`, `p` = the command author, `h`, `zr-op`."""
    return [["e", _hex64(root_event_id, "root_event_id"), "", "root"],
            ["e", _hex64(command_event_id, "command_event_id"), "", "reply"],
            ["p", _hex64(command_author, "command_author")], ["h", _text(channel, "channel")],
            ["zr-op", receipt_op(command_id, revision)]]


def receipt_op(command_id: str, revision: int) -> str:
    """The logical identity of a receipt: `receipt:<command_id>:<transition_revision>` (§6.1.4)."""
    _text(command_id, "command_id")
    return "receipt:" + command_id + ":" + str(_revision(revision))


def _revision(revision: object) -> int:
    # REFUSE-READING: "strictly increasing per command" starts at 1; 0 is never a transition.
    if _int(revision, "transition_revision") < 1:
        raise ContractError("buzz projection: transition_revision starts at 1")
    return revision


def resolve_thread(tags: list) -> tuple[str, str] | None:
    """Buzz's NIP-10 resolution (`buzz-core nip10.rs`, RESEARCH-B B3): (root, parent), or None for a top-level post.

    `root`+`reply` -> (root, parent); `reply` only -> (reply, reply); `root` only or neither -> None. A marker
    counts only with a 64-hex id; the last valid occurrence wins.
    """
    root = reply = None
    for tag in tags:
        if len(tag) >= 4 and tag[0] == "e" and isinstance(tag[1], str) and _HEX64.fullmatch(tag[1]):
            if tag[3] == "root":
                root = tag[1]
            elif tag[3] == "reply":
                reply = tag[1]
    if reply is None:
        return None
    return (root or reply, reply)


# --- builders ----------------------------------------------------------------------------------------------------

def task_root(*, task_id: str, title: str, team: str, assignee: str, channel: str, created_at: int) -> dict:
    """The thread-root kind 9 (§4.1): the `zeus:task-root` fence, `zr-op = "root:" + task_id` and `h`. No `e` tag."""
    body = {"schema": TASK_ROOT_SCHEMA, "task_id": _text(task_id, "task_id"),
            "title": _text(title, "title", limit=MAX_TITLE_CHARS), "team": _text(team, "team"),
            "assignee": _text(assignee, "assignee")}
    tags = [["h", _text(channel, "channel")], ["zr-op", "root:" + task_id]]
    return _event(KIND_POST, created_at, tags, _fence("zeus:task-root", body))


def _intervention(item: object) -> dict:
    _exact(item, frozenset({"op", "available", "reason_code"}), "intervention")
    if item["op"] not in rc.OPS or not isinstance(item["available"], bool):
        raise ContractError("buzz projection: intervention needs a known op and a boolean available")
    code = item["reason_code"]
    if code is not None and code not in rc.REFUSAL_CODES:
        raise ContractError("buzz projection: intervention reason_code is not a refusal code")
    if not item["available"] and code is None:  # REFUSE-READING: an unavailable button says why
        raise ContractError("buzz projection: an unavailable intervention needs a reason_code")
    return {"op": item["op"], "available": item["available"], "reason_code": code}


def _card_content(task: dict) -> dict:
    _exact(task, _CARD_KEYS, "task")
    refs = task["evidence_refs"]
    if not isinstance(refs, list) or len(refs) > MAX_EVIDENCE_REFS or not all(evidence_ref_ok(r) for r in refs):
        raise ContractError("buzz projection: evidence_refs must be a short list of opaque ids (no paths)")
    if not isinstance(task["interventions"], list):
        raise ContractError("buzz projection: interventions must be a list")
    return {"schema": TASK_SCHEMA, "task_id": _text(task["task_id"], "task_id"),
            "version": _int(task["version"], "version"), "generation": _int(task["generation"], "generation"),
            "status": _text(task["status"], "status"), "assignee": _text(task["assignee"], "assignee"),
            "sender": _text(task["sender"], "sender"), "team": _text(task["team"], "team"),
            "stage": _opt_text(task["stage"], "stage"), "updated_at": _int(task["updated_at"], "updated_at"),
            "observed_at": _int(task["observed_at"], "observed_at"),
            "summary": _text(task["summary"], "summary", limit=MAX_SUMMARY_CHARS, empty=True),
            "evidence_refs": list(refs), "interventions": [_intervention(i) for i in task["interventions"]]}


def _artifact_tags(d: str, channel: str, kind_name: str, op: str, prev: str | None, *, title: str | None = None,
                   root: str | None = None) -> list:
    if op not in CARD_OPS:
        raise ContractError("buzz projection: op must be create or update")
    if (op == "update") != (prev is not None):  # REFUSE-READING: `prev` exactly when not create (§4.5)
        raise ContractError("buzz projection: prev is required for update and forbidden for create")
    tags = [["ar", "1"], ["d", d], ["h", _text(channel, "channel")], ["type", kind_name]]
    if title is not None:
        tags.append(["title", _text(title, "title", limit=MAX_TITLE_CHARS)])
    tags.append(["op", op])
    if root is not None:
        tags.append(["root", _hex64(root, "root_event_id")])
    if prev is not None:
        tags.append(["prev", _hex64(prev, "prev")])
    return tags


def task_card(*, task: dict, title: str, recipient_role: str, channel: str, root_event_id: str, created_at: int,
              op: str = "create", prev: str | None = None) -> dict:
    """The `zeus.task` 45010 (§4.5): tags ar, d, h, type, title, op, root, prev (not create), zt, zs, zr."""
    content = _card_content(task)
    tags = _artifact_tags(task_artifact_d(content["task_id"]), channel, "zeus.task", op, prev, title=title,
                          root=root_event_id)
    tags += [["zt", content["task_id"]], ["zs", content["status"]], ["zr", _text(recipient_role, "recipient_role")]]
    return _event(KIND_ARTIFACT, created_at, tags, _bounded(_canonical(content)))


def _role(role: object) -> dict:
    _exact(role, _ROLE_KEYS, "role")
    status = _exact(role["status"], _ROLE_STATUS_KEYS, "role status")
    if status["state"] not in ORG_STATES:
        raise ContractError("buzz projection: role state is not one of idle|busy|paused|unknown")
    return {"id": _text(role["id"], "role id"), "role": _text(role["role"], "role"),
            "parent": _opt_text(role["parent"], "parent"), "team": _text(role["team"], "team"),
            "display": _text(role["display"], "display"), "pubkey": _hex64(role["pubkey"], "role pubkey"),
            "status": {"state": status["state"], "task_id": _opt_text(status["task_id"], "status task_id"),
                       "last_activity_at": _opt_int(status["last_activity_at"], "last_activity_at"),
                       "observed_at": _int(status["observed_at"], "observed_at")}}


def org_snapshot(*, org: dict, d: str, channel: str, created_at: int, op: str = "create",
                 prev: str | None = None) -> dict:
    """The `zeus.org` 45010 (§4.2). `d` is the PINNED org artifact id from configuration (§2 rule 4), not derived.

    The `op`/`prev` tags follow the same NIP-AR revision rule as a card (§6.1.4: `prev` is the current relay head).
    The signed snapshot carries no `fresh` claim.
    """
    _exact(org, _ORG_KEYS, "org")
    fleet = _exact(org["fleet"], _FLEET_KEYS, "fleet")
    if not isinstance(org["roles"], list):
        raise ContractError("buzz projection: roles must be a list")
    content = {"schema": ORG_SCHEMA, "version": _int(org["version"], "version"),
               "generated_at": _int(org["generated_at"], "generated_at"),
               "roles": [_role(r) for r in org["roles"]],
               "fleet": {"paused": _opt_bool(fleet["paused"], "fleet paused"),
                         "version": _opt_int(fleet["version"], "fleet version"),
                         "activation_hold": _opt_bool(fleet["activation_hold"], "activation_hold")}}
    tags = _artifact_tags(_text(d, "d"), channel, "zeus.org", op, prev, title=ORG_TITLE)
    return _event(KIND_ARTIFACT, created_at, tags, _bounded(_canonical(content)))


def _work(work: object) -> dict | None:
    if work is None:
        return None
    _exact(work, _WORK_KEYS, "work")
    state, result, evidence_at = work["state"], work["result"], work["evidence_at"]
    if state not in rc.WORK_STATES:
        raise ContractError("buzz projection: work state is not in the §4.4 vocabulary")
    # §4.4: `completed` carries the exact desk result; nothing else carries one.
    if (state == "completed") != (result is not None) or (result is not None and result not in rc.WORK_RESULTS):
        raise ContractError("buzz projection: only `completed` carries a result of answered|needs_spec")
    if state == "running" and evidence_at is None:  # §4.4: `running` only with execution evidence
        raise ContractError("buzz projection: running needs evidence_at")
    return {"state": state, "result": result, "evidence_at": _opt_int(evidence_at, "evidence_at")}


def receipt(*, command_id: str, command_event_id: str, command_author: str, root_event_id: str, channel: str,
            transition_revision: int, disposition: str, reason_code: str | None = None, task_id: str | None = None,
            generation_after: int | None = None, work: dict | None = None, at: int, created_at: int) -> dict:
    """The `zeus:receipt` kind 9 (§4.4): the fence, `zr-op = "receipt:<command_id>:<revision>"`, QB1 thread tags."""
    try:
        valid_id = uuid.UUID(command_id).version == 4 and str(uuid.UUID(command_id)) == command_id
    except (ValueError, AttributeError, TypeError):
        valid_id = False
    if not valid_id:
        raise ContractError("buzz projection: command_id must be a canonical uuid v4")
    if disposition not in rc.DISPOSITIONS:
        raise ContractError("buzz projection: disposition is not in the §4.4 set")
    if reason_code is not None and reason_code not in rc.REFUSAL_CODES:
        raise ContractError("buzz projection: reason_code is not a refusal code")
    # REFUSE-READING: a refusal names its code; a done effect names none.
    if (disposition == "refused" and reason_code is None) or (disposition == "effect_done" and reason_code):
        raise ContractError("buzz projection: refused needs a reason_code; effect_done takes none")
    body = {"schema": RECEIPT_SCHEMA, "command_id": command_id, "command_event_id": _hex64(
        command_event_id, "command_event_id"), "transition_revision": _revision(transition_revision),
            "disposition": disposition, "reason_code": reason_code, "task_id": _opt_text(task_id, "task_id"),
            "generation_after": _opt_int(generation_after, "generation_after"), "work": _work(work),
            "at": _int(at, "at")}
    tags = receipt_tags(channel, root_event_id, command_event_id, command_author, command_id, transition_revision)
    return _event(KIND_POST, created_at, tags, _fence("zeus:receipt", body))


# --- coalescing and interventions ---------------------------------------------------------------------------------

def may_publish(subject_kind: str, last_published_at: int | None, now: int, terminal: bool = False) -> bool:
    """§6.3: org revisions >= 10 s apart, task revisions >= 2 s; a terminal transition is immediate."""
    periods = {"org": ORG_MIN_PERIOD, "task": TASK_MIN_PERIOD}
    if subject_kind not in periods:
        raise ContractError("buzz projection: subject_kind must be org or task")
    _int(now, "now")
    _opt_int(last_published_at, "last_published_at")
    if terminal is True or last_published_at is None:
        return True
    return now - last_published_at >= periods[subject_kind]  # a clock behind the last publish waits


def interventions(task_view: dict | None, fleet_view: dict | None) -> list:
    """Button availability: `[{op, available, reason_code}]` for the five ops, in `rc.OPS` order.

    `task_view`: `{terminal: bool}` or None (the task is unknown). `fleet_view`: `{paused, activation_hold}` where
    None values mean the row was unreadable. An unknown fleet state is unavailable, never optimistic (REFUSE-READING).
    The bridge re-validates every command regardless (§4.5). Desk ops stay unavailable until S8 (DESIGN-B §1).
    """
    def item(op: str, available: bool, code: str | None = None) -> dict:
        return {"op": op, "available": available, "reason_code": None if available else code}

    out = []
    if not isinstance(task_view, dict):
        out.append(item("cancel_task", False, rc.TASK_UNKNOWN))
    elif task_view.get("terminal") is True:
        out.append(item("cancel_task", False, rc.NOT_APPLIED))
    elif task_view.get("terminal") is False:
        out.append(item("cancel_task", True))
    else:
        out.append(item("cancel_task", False, rc.TASK_UNKNOWN))
    paused = fleet_view.get("paused") if isinstance(fleet_view, dict) else None
    hold = fleet_view.get("activation_hold") if isinstance(fleet_view, dict) else None
    out.append(item("pause_fleet", paused is False, rc.NOT_APPLIED))
    if hold is True:
        out.append(item("resume_fleet", False, rc.ACTIVATION_HOLD_PRESENT))
    else:
        out.append(item("resume_fleet", paused is True and hold is False, rc.NOT_APPLIED))
    for op in ("desk_open", "desk_turn"):
        out.append(item(op, DESK_MIGRATED, rc.DESK_NOT_MIGRATED))
    return out
