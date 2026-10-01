"""Remote control (Buzz): the `zeus:command` envelope, owner decision, admission freshness and the disposition machine.

Layer: domain
Context: coordination
Owns: `parse_command` (the fence and the §4.3 schema `urn:zeus:buzz-command:1`), `command_digest` (canonical-JSON
    content digest for replay/alias/conflict), `owner_allowed`, `fresh_for_admission`, the disposition state machine
    (`next_transition`, `TERMINAL`), the work-state vocabulary and the refusal-code constants
Does not own: the `RemoteControl.admit` use case, its transaction, the bridge fence and the bound-result reads (B3),
    the stores and buckets, signature verification (observation), the receipt event (observation `buzz_projection`)
Entry points: parse_command, command_digest, owner_allowed, fresh_for_admission, next_transition, Refusal,
    DISPOSITIONS, TERMINAL, WORK_STATES, OPS, REFUSAL_CODES
Contracts: Buzz DESIGN §4.3/§4.4 (command, receipt, dispositions), §6.2.2-§6.2.3 (owner filter, admission order,
    freshness for NEW admission only), §6.4 (refusal codes) in
    aibox-migration-001/evidence/buzz-zeus-localization-001/DESIGN.md; Batch B DESIGN-B §1-§2

Pure policy over strings and dictionaries. Where §4.3 is silent the reading that refuses wins (marked "REFUSE-READING").
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from codex_harness.kernel.errors import ContractError

COMMAND_SCHEMA_PREFIX = "urn:zeus:buzz-command:"
COMMAND_MAJOR = 1
COMMAND_TTL = 600  # §6.2.3(iii): seconds, NEW admission only
ISSUED_AT_SKEW = 5  # §4.3: issued_at = created_at ±5 s
MAX_REASON_CHARS = 500  # §4.3
MAX_SESSION_ID_CHARS = 128  # REFUSE-READING: §4.3 gives `desk.session_id` no bound; a declared one
MAX_COMMAND_CONTENT_BYTES = 65536  # declared bound on one command event content (artifacts stay < 256 KiB)

OPS = ("cancel_task", "pause_fleet", "resume_fleet", "desk_open", "desk_turn")
DESK_INTENTS = ("consult", "request")

# Dispositions (§4.4): the COMMAND's state, forward-only (§6.2).
DISPOSITIONS = ("received", "accepted", "refused", "effect_done", "effect_unknown")
TERMINAL = frozenset({"effect_done", "refused"})
_TRANSITIONS = {
    "received": frozenset({"accepted", "refused", "effect_done", "effect_unknown"}),
    "accepted": frozenset({"effect_done", "refused", "effect_unknown"}),
    "effect_unknown": frozenset({"effect_done", "refused"}),
    "effect_done": frozenset(),
    "refused": frozenset(),
}

# The separate WORK lifecycle (§4.4, F3).
WORK_STATES = ("queued", "claimed", "running", "completed", "refused", "unknown")
WORK_RESULTS = ("answered", "needs_spec")  # `completed`: consult -> answered, request -> needs_spec

# §4.3 / §6.4 refusal codes.
STALE_GENERATION = "stale_generation"
STALE_CONTROL = "stale_control"
ACTIVATION_HOLD_PRESENT = "activation_hold_present"
COMMAND_EXPIRED = "command_expired"
COMMAND_CONFLICT = "command_conflict"
INVALID_COMMAND = "invalid_command"
UNSUPPORTED_VERSION = "unsupported_version"
TASK_UNKNOWN = "task_unknown"
ROLE_UNKNOWN = "role_unknown"
SESSION_CONFLICT = "session_conflict"
REQUEST_CONFLICT = "request_conflict"
SESSION_BUSY = "session_busy"
SESSION_UNKNOWN = "session_unknown"
NOT_APPLIED = "not_applied"
DESK_NOT_MIGRATED = "desk_not_migrated"
REFUSAL_CODES = frozenset({
    STALE_GENERATION, STALE_CONTROL, ACTIVATION_HOLD_PRESENT, COMMAND_EXPIRED, COMMAND_CONFLICT, INVALID_COMMAND,
    UNSUPPORTED_VERSION, TASK_UNKNOWN, ROLE_UNKNOWN, SESSION_CONFLICT, REQUEST_CONFLICT, SESSION_BUSY,
    SESSION_UNKNOWN, NOT_APPLIED, DESK_NOT_MIGRATED})
IGNORED_NOT_OWNER = "ignored_not_owner"  # an inbox outcome (§6.2.2), never a receipt

_FENCE = re.compile(r"```zeus:command[ \t]*\r?\n(.*?)```", re.DOTALL)
_SCHEMA = re.compile(re.escape(COMMAND_SCHEMA_PREFIX) + r"(0|[1-9][0-9]*)")  # REFUSE-READING: one spelling per major
_HEX64 = re.compile(r"[0-9a-f]{64}")
_COMMON = frozenset({"schema", "command_id", "op", "task_id", "expected_generation", "expected_control", "reason",
                     "desk", "issued_at"})


@dataclass(frozen=True)
class Refusal:
    """A refused command: `code` is one of `REFUSAL_CODES`; `detail` is diagnostic text only."""

    code: str
    detail: str = ""


def _refuse(code: str, detail: str) -> Refusal:
    return Refusal(code, detail)


def _reject_constant(name: str):
    raise ValueError(f"non-finite number {name}")


def _no_duplicates(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:  # REFUSE-READING: a duplicate key makes the signed content ambiguous
            raise ValueError(f"duplicate key {key}")
        out[key] = value
    return out


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def command_digest(command: dict) -> str:
    """SHA-256 hex of the canonical JSON (sorted keys, no whitespace, UTF-8) of a command object (§4 preamble).

    Decides replay (same digest), alias (same digest, another event id) and conflict (another digest) in §6.2.3(ii).
    """
    try:
        canonical = json.dumps(command, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                               allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ContractError("remote control: command is not canonical JSON") from exc
    return hashlib.sha256(canonical).hexdigest()


def _parse_issued_at(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:  # REFUSE-READING: a zone-less time is ambiguous
        return None
    return parsed.timestamp()


def _check_control(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == {"paused", "version"} and isinstance(value["paused"], bool)
            and _is_int(value["version"]))


def _check_desk(op: str, value: object) -> str | None:
    """The refusal detail for a bad `desk` object, else None."""
    if not isinstance(value, dict) or set(value) != {"session_id", "title", "intent", "text"}:
        return "desk must be an object with session_id, title, intent, text"
    session_id, title, intent, text = value["session_id"], value["title"], value["intent"], value["text"]
    if not isinstance(session_id, str) or not session_id or len(session_id) > MAX_SESSION_ID_CHARS:
        return "desk.session_id must be a non-empty string"
    if title is not None and not isinstance(title, str):
        return "desk.title must be a string or null"
    if op == "desk_open":  # REFUSE-READING: open carries session+title only
        if intent is not None or text is not None:
            return "desk_open takes no intent or text"
        return None
    if intent not in DESK_INTENTS:
        return "desk_turn needs an intent of consult or request"
    if not isinstance(text, str) or not text:
        return "desk_turn needs non-empty text"
    return None


def parse_command(event_content: str, *, created_at: int) -> dict | Refusal:
    """Extract and validate the `zeus:command` fence of a kind-9 content (§4.3). Returns the command dict or a Refusal.

    `invalid_command`: no or several fences, malformed JSON, a missing/ill-typed field, an op-specific field set that
    does not match the op, `issued_at` outside created_at ±5 s. `unsupported_version`: a well-formed schema URN
    with another MAJOR. Unknown extra keys are kept (minor additions are optional fields, §4) and are part of the
    digest.
    """
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0:
        raise ContractError("remote control: created_at must be a non-negative integer")
    if not isinstance(event_content, str):
        return _refuse(INVALID_COMMAND, "content must be a string")
    if len(event_content.encode("utf-8", "surrogatepass")) > MAX_COMMAND_CONTENT_BYTES:
        return _refuse(INVALID_COMMAND, "content exceeds the declared bound")
    fences = _FENCE.findall(event_content)
    if len(fences) != 1:  # REFUSE-READING: zero or several fences are not one command
        return _refuse(INVALID_COMMAND, "exactly one zeus:command fence is required")
    try:
        command = json.loads(fences[0], object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
        command_digest(command)  # canonical-JSON encodable (rejects lone surrogates)
    except (ValueError, ContractError) as exc:
        return _refuse(INVALID_COMMAND, f"fence is not canonical JSON: {exc}")
    if not isinstance(command, dict):
        return _refuse(INVALID_COMMAND, "command must be a JSON object")

    schema = command.get("schema")
    match = _SCHEMA.fullmatch(schema) if isinstance(schema, str) else None
    if match is None:
        return _refuse(INVALID_COMMAND, "schema must be urn:zeus:buzz-command:<major>")
    if int(match.group(1)) != COMMAND_MAJOR:
        return _refuse(UNSUPPORTED_VERSION, f"unsupported command major {match.group(1)}")

    command_id = command.get("command_id")
    try:
        parsed_id = uuid.UUID(command_id) if isinstance(command_id, str) else None
    except ValueError:
        parsed_id = None
    # REFUSE-READING: the canonical lowercase hyphenated form only, so one id has one spelling.
    if parsed_id is None or parsed_id.version != 4 or parsed_id.variant != uuid.RFC_4122 or str(parsed_id) != command_id:
        return _refuse(INVALID_COMMAND, "command_id must be a canonical uuid v4")

    op = command.get("op")
    if op not in OPS:
        return _refuse(INVALID_COMMAND, "op is not a known command")

    reason = command.get("reason")
    if not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS:
        return _refuse(INVALID_COMMAND, f"reason must be a string of at most {MAX_REASON_CHARS} characters")

    issued = _parse_issued_at(command.get("issued_at"))
    if issued is None:
        return _refuse(INVALID_COMMAND, "issued_at must be an ISO time with a zone")
    if abs(issued - created_at) > ISSUED_AT_SKEW:
        return _refuse(INVALID_COMMAND, "issued_at is not within 5 s of created_at")

    # REFUSE-READING: the per-op field sets are exact; a field of another op must be absent or null.
    task_id, generation = command.get("task_id"), command.get("expected_generation")
    control, desk = command.get("expected_control"), command.get("desk")
    if op == "cancel_task":
        if not isinstance(task_id, str) or not task_id:
            return _refuse(INVALID_COMMAND, "cancel_task requires task_id")
        if not _is_int(generation):
            return _refuse(INVALID_COMMAND, "cancel_task requires expected_generation")
        if control is not None or desk is not None:
            return _refuse(INVALID_COMMAND, "cancel_task takes no expected_control or desk")
    elif op in ("pause_fleet", "resume_fleet"):
        if not _check_control(control):
            return _refuse(INVALID_COMMAND, f"{op} requires expected_control {{paused, version}}")
        if task_id is not None or generation is not None or desk is not None:
            return _refuse(INVALID_COMMAND, f"{op} takes no task_id, expected_generation or desk")
    else:
        detail = _check_desk(op, desk)
        if detail is not None:
            return _refuse(INVALID_COMMAND, detail)
        if task_id is not None or generation is not None or control is not None:
            return _refuse(INVALID_COMMAND, f"{op} takes no task_id, expected_generation or expected_control")
    return command


def owner_allowed(author_hex: str, allowlist) -> bool:
    """§6.2.2: only an allowlisted owner key may issue commands; anyone else is `ignored_not_owner` (no receipt).

    Exact lowercase 64-hex match; a malformed author or allowlist entry never matches.
    """
    if not isinstance(author_hex, str) or _HEX64.fullmatch(author_hex) is None:
        return False
    return any(isinstance(entry, str) and entry == author_hex for entry in allowlist)


def fresh_for_admission(received_at: int, created_at: int, ttl: int = COMMAND_TTL) -> bool:
    """§6.2.3(iii): `|received_at - created_at| <= ttl`. Applies ONLY to NEW admission, never to a replay or a resume."""
    for name, value in (("received_at", received_at), ("created_at", created_at), ("ttl", ttl)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractError(f"remote control: {name} must be a non-negative integer")
    return abs(received_at - created_at) <= ttl


def next_transition(current: str, target: str) -> bool:
    """True iff a command may move `current -> target` (§4.4, §6.2); terminal states and any repeat are False."""
    for name, value in (("current", current), ("target", target)):
        if value not in _TRANSITIONS:
            raise ContractError(f"remote control: unknown disposition {name}={value!r}")
    return target in _TRANSITIONS[current]
