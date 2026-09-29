"""Activity projection of the provider stream into execution_progress rows (INV-OBSERVATION-001).

Layer: domain
Context: execution
Owns: the activity projection of the provider stream into execution_progress rows (M7 `domain/progress_activity.py`,
    moved in S4 unchanged; named coverage correction observation->execution, DESIGN-run-task D1)
Does not own: the monitor's read model (observation, S9)
Entry points: activity_label, claude_result_status, build_receipt, validate_receipt, fixed_last_event,
    fixed_completed_type, fixed_completed_status, ActivityInvalid
Contracts: INV-OBSERVATION-001

Compact activity receipts and fixed progress labels (S2b, FLEET-S2B-SPEC): pure rules, no IO.

A retained runtime event keeps its raw receipt exactly as FA-016 records it. Beside it the executor may write ONE
compact activity receipt: a new object built only from fixed vocabularies, a built-in tool name, lease lineage,
the executor's collection time and internal references. It is a bounded display record (the activity pane reads it
instead of a raw body that can be megabytes), never evidence of progress or acceptance, and it never carries
payload, text, commands, paths, provider ids, subtypes or reasoning.

The same module owns the fixed vocabulary the monitor projects for the S1a progress labels, so no external text
(a provider subtype, an unknown method) reaches a session view.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from codex_harness.execution.domain.provider_stream import CodexStream
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical

ACTIVITY_SCHEMA = "urn:zeus:progress-activity:1"
ACTIVITY_RING = 6
ACTIVITY_BODY_BYTES = 65_536
CLAUDE, CODEX = "claude_cli", "app_server"
# Display labels only, never grants; anything else (custom and MCP names included) is null, never truncated text.
BUILTIN_TOOLS = frozenset({"Read", "Glob", "Grep", "Bash", "Edit", "Write", "NotebookEdit", "Task", "WebFetch",
                           "WebSearch", "StructuredOutput"})
CODEX_ITEM_TYPES = frozenset({"commandExecution", "fileChange", "mcpToolCall", "agentMessage", "reasoning"})
CLAUDE_ACTIVITY = ("session_started", "tool_started", "tool_completed", "permission_denied", "result")
TOOL_STARTED = "tool_started"
ITEM_COMPLETED = "item_completed"
EVENT_LABELS = {CLAUDE: frozenset(CLAUDE_ACTIVITY), CODEX: frozenset({ITEM_COMPLETED})}
STATUSES = {"session_started": {"started"}, "tool_started": {"started"}, "permission_denied": {"denied"},
            "tool_completed": {"completed", "failed", "unknown"}, "result": {"success", "error", "unknown"},
            "item_completed": {"completed", "failed", "unknown", None}}
RECEIPT_KEYS = frozenset({"schema", "execution", "transport", "event_label", "tool_name", "item_type", "status",
                          "activity_sequence", "progress_sequence", "generation", "attempt", "collected_at",
                          "occurred_at", "raw_ref"})
ARTIFACT_REF = re.compile(r"sha256:[0-9a-f]{64}")


class ActivityInvalid(ContractError):
    """A fixed reason code for a compact record that cannot be built or read; never payload text."""

    def __init__(self, code: str):
        super().__init__("activity receipt invalid: " + code)
        self.code = code


def activity_label(transport: str, event) -> str | None:
    """The activity label of an event the pane shows, or None. Codex token updates and malformed events never
    take a compact slot (they stay raw-only), and Claude messages are not retained."""
    if not isinstance(event, dict):
        return None
    if transport == CLAUDE:
        kind = event.get("type")
        return kind if type(kind) is str and kind in EVENT_LABELS[CLAUDE] else None
    if transport == CODEX:
        return ITEM_COMPLETED if event.get("method") == "item/completed" else None
    return None


def claude_result_status(event) -> str:
    """The Claude adapter's own failure rule (`claude_cli` result handling): a result fails when `raw.is_error` is
    truthy or the normalized status is not `success`. Only the truthiness of that ONE raw key is read, after the
    raw line is proven an object (FLEET-S2B-SPEC D9 amends FLEET-S2-SPEC §2 for the producer only)."""
    raw = event.get("raw") if isinstance(event, dict) else None
    if type(raw) is not dict:
        return "unknown"
    return "error" if bool(raw.get("is_error")) or event.get("status") != "success" else "success"


def _status(transport: str, label: str, event: dict):
    if label in ("session_started", "tool_started"):
        return "started"
    if label == "permission_denied":
        return "denied"
    if label == "tool_completed":
        status = event.get("status")
        return status if type(status) is str and status in ("completed", "failed") else "unknown"
    if label == "result":
        return claude_result_status(event)
    item = (event.get("params") or {}).get("item") or {}
    status = item.get("status")
    if status is None:
        return None
    return status if type(status) is str and status in ("completed", "failed") else "unknown"


def _aware(value) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ActivityInvalid("collected_at") from None
    if moment.utcoffset() is None:
        raise ActivityInvalid("collected_at")
    return moment.astimezone(timezone.utc).isoformat()


def _count(value, field: str, minimum: int, nullable: bool = False):
    if value is None and nullable:
        return None
    if type(value) is not int or value < minimum:
        raise ActivityInvalid(field)
    return value


def build_receipt(*, execution, transport, event, activity_sequence, progress_sequence, generation, attempt,
                  collected_at, raw_ref) -> dict:
    """ONE compact record: a new object, never a redacted copy of the event. Raises ActivityInvalid (a fixed
    code) when the internal metadata is not what the contract allows; the caller drops only the activity."""
    label = activity_label(transport, event)
    if label is None:
        raise ActivityInvalid("not_activity")
    tool = event.get("tool") if label == TOOL_STARTED else None
    if transport == CLAUDE:
        item_type, occurred = None, None  # a Claude line carries no occurrence time; a supplied one is ignored
    else:
        item = (event.get("params") or {}).get("item") or {}
        kind = item.get("type")
        item_type = kind if type(kind) is str and kind in CODEX_ITEM_TYPES else "unknown"
        occurred = CodexStream.occurrence(event)
    document = {"schema": ACTIVITY_SCHEMA, "execution": execution, "transport": transport, "event_label": label,
                "tool_name": tool if type(tool) is str and tool in BUILTIN_TOOLS else None,
                "item_type": item_type, "status": _status(transport, label, event),
                "activity_sequence": activity_sequence, "progress_sequence": progress_sequence,
                "generation": generation, "attempt": attempt,
                "collected_at": _aware(collected_at), "occurred_at": occurred, "raw_ref": raw_ref}
    return validate_receipt(document)


def validate_receipt(document) -> dict:
    """The exact contract of a compact record, for the builder and for every reader. Exact types are checked
    before any set lookup, so a list or object can never raise out of a per-entry boundary."""
    if not isinstance(document, dict) or set(document) != RECEIPT_KEYS:
        raise ActivityInvalid("keys")
    if document["schema"] != ACTIVITY_SCHEMA:
        raise ActivityInvalid("schema")
    execution = document["execution"]
    if type(execution) is not str or not execution:
        raise ActivityInvalid("execution")
    transport, label = document["transport"], document["event_label"]
    if type(transport) is not str or transport not in EVENT_LABELS:
        raise ActivityInvalid("transport")
    if type(label) is not str or label not in EVENT_LABELS[transport]:
        raise ActivityInvalid("event_label")
    tool = document["tool_name"]
    if tool is not None and not (label == TOOL_STARTED and type(tool) is str and tool in BUILTIN_TOOLS):
        raise ActivityInvalid("tool_name")
    item_type = document["item_type"]
    if transport == CLAUDE and item_type is not None:
        raise ActivityInvalid("item_type")
    if transport == CODEX and not (type(item_type) is str and (item_type in CODEX_ITEM_TYPES or item_type == "unknown")):
        raise ActivityInvalid("item_type")
    status = document["status"]
    if not (status is None or type(status) is str) or status not in STATUSES[label]:
        raise ActivityInvalid("status")
    _count(document["activity_sequence"], "activity_sequence", 1)
    start = label == TOOL_STARTED
    if start:
        if document["progress_sequence"] is not None or document["raw_ref"] is not None:
            raise ActivityInvalid("start_raw")
    else:
        _count(document["progress_sequence"], "progress_sequence", 1)
        raw_ref = document["raw_ref"]
        if type(raw_ref) is not str or not ARTIFACT_REF.fullmatch(raw_ref):
            raise ActivityInvalid("raw_ref")
    _count(document["generation"], "generation", 0, nullable=True)
    _count(document["attempt"], "attempt", 0, nullable=True)
    if type(document["collected_at"]) is not str or _aware(document["collected_at"]) != document["collected_at"]:
        raise ActivityInvalid("collected_at")
    occurred = document["occurred_at"]
    if occurred is not None:
        valid = transport == CODEX and type(occurred) is str
        try:
            valid = valid and _aware(occurred) == occurred
        except ActivityInvalid:
            valid = False
        if not valid:
            raise ActivityInvalid("occurred_at")
    if len(canonical(document).encode("utf-8")) > ACTIVITY_BODY_BYTES:
        raise ActivityInvalid("too_large")
    return document


# ----- fixed S1a progress labels (FLEET-S2B-SPEC §4, D10) ----------------------------------------------------------
LAST_EVENT_EXACT = frozenset({"item/completed", "thread/tokenUsage/updated", "claude/system/init",
                              "claude/system/permission_denied"})
CLAUDE_BASES = ("claude/system", "claude/user", "claude/assistant", "claude/result", "claude/malformed")
COMPLETED_TYPES = frozenset({*CLAUDE_ACTIVITY, "message", *CODEX_ITEM_TYPES})
COMPLETED_STATUSES = frozenset({"started", "completed", "failed", "denied", "emitted", "success", "error", "unknown"})


def fixed_last_event(value):
    """A progress label from the fixed vocabulary; a provider subtype suffix collapses to its base, never text."""
    if value is None:
        return None
    if type(value) is not str:
        return "unknown"
    if value in LAST_EVENT_EXACT:
        return value
    for base in CLAUDE_BASES:
        if value == base or value.startswith(base + "/"):
            return base
    return "unknown"


def fixed_completed_type(value):
    if value is None:
        return None
    return value if type(value) is str and value in COMPLETED_TYPES else "unknown"


def fixed_completed_status(value):
    if value is None:
        return None
    if type(value) is not str:
        return "unknown"
    if value in COMPLETED_STATUSES:
        return value
    return "error" if value.startswith("error") else "unknown"


__all__ = ["ACTIVITY_BODY_BYTES", "ACTIVITY_RING", "ACTIVITY_SCHEMA", "ActivityInvalid", "BUILTIN_TOOLS", "CLAUDE",
           "CODEX", "CODEX_ITEM_TYPES", "TOOL_STARTED", "activity_label", "build_receipt", "claude_result_status",
           "fixed_completed_status", "fixed_completed_type", "fixed_last_event", "validate_receipt"]
