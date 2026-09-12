"""Reading a provider's event stream without pretending one provider is another.

Each transport speaks its own protocol. The harness records progress, occurrence times and event
identity from all of them, so it needs one question set — is this event well formed, is it worth
recording, when did it happen, what makes it the same event on redelivery — answered per provider
rather than a single shape that a second provider has to be bent into.

The Codex reader keeps the App Server's own JSON-RPC notifications. The Claude reader works on
events the CLI adapter has already normalized, and its labels stay namespaced (`claude/assistant`)
so nothing downstream can mistake a Claude line for a notification a Codex server actually sent
(INV-CLAUDE-WORKER-001).
"""
from __future__ import annotations

from datetime import datetime, timezone

CODEX_PROGRESS = ("item/completed", "thread/tokenUsage/updated")
CLAUDE_PROGRESS = ("session_started", "tool_completed", "permission_denied", "result")
TOOL_ITEM_TYPES = ("commandExecution", "fileChange", "mcpToolCall")


def epoch_millis(candidate) -> str | None:
    """A UTC timestamp from an epoch-millisecond field, or None; never the collection moment."""
    if type(candidate) is int and 0 < candidate < 10**14:
        return datetime.fromtimestamp(candidate / 1000, tz=timezone.utc).isoformat()
    return None


class CodexStream:
    """Codex App Server notifications, exactly as the server sends them."""

    identity = "codex-app-server"
    transport = "app_server"

    @staticmethod
    def shape(event) -> str | None:
        """Name what is wrong with a runtime event before anything reads into it; None means well-formed.

        Review counterexample (PR #49): `method=[]` raised inside set membership and `item="garbage"`
        advanced the sequence. A progress event is a dict whose method is text, whose params is a dict,
        and whose per-method payload has the identifiers the reader will use.
        """
        if not isinstance(event, dict):
            return "event is not an object"
        method = event.get("method")
        if not isinstance(method, str) or not method:
            return "method is not text"
        params = event.get("params", {})
        if not isinstance(params, dict):
            return "params is not an object"
        if method == "item/completed":
            item = params.get("item")
            if not isinstance(item, dict):
                return "item is not an object"
            if not isinstance(item.get("id"), str) or not item["id"]:
                return "item.id missing"
            if not isinstance(item.get("type"), str) or not item["type"]:
                return "item.type missing"
            if "status" in item and not isinstance(item["status"], str):
                return "item.status is not text"
        elif method == "thread/tokenUsage/updated":
            if not isinstance(params.get("tokenUsage"), dict):
                return "tokenUsage is not an object"
        return None

    @staticmethod
    def is_progress(event) -> bool:
        return isinstance(event, dict) and event.get("method") in CODEX_PROGRESS

    @staticmethod
    def occurrence(event) -> str | None:
        """The event's own UTC occurrence time, or None; the collection moment never stands in for it."""
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        for candidate in (params.get("completedAtMs"), item.get("completedAtMs"), event.get("emittedAtMs")):
            moment = epoch_millis(candidate)
            if moment is not None:
                return moment
        return None

    @staticmethod
    def event_id(event: dict, receipt_ref: str) -> str:
        """Unique per delivered event: runtime item identity when present, else the retained bytes."""
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        if isinstance(item.get("id"), str) and item["id"]:
            return f"{event.get('method')}:{item['id']}:{item.get('status')}"
        return f"{event.get('method')}:{receipt_ref}"

    @staticmethod
    def label(event) -> str:
        return str(event.get("method")) if isinstance(event, dict) else "malformed"

    @staticmethod
    def item_field(event, name: str):
        params = event.get("params") if isinstance(event, dict) and isinstance(event.get("params"), dict) else {}
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        value = item.get(name)
        return value if type(value) is str and value else None

    @classmethod
    def item_type(cls, event):
        return cls.item_field(event, "type")

    @classmethod
    def item_status(cls, event):
        return cls.item_field(event, "status")

    @staticmethod
    def tool_items(events) -> int:
        return sum(1 for event in events if isinstance(event, dict) and event.get("method") == "item/completed"
                   and (event.get("params") or {}).get("item", {}).get("type") in TOOL_ITEM_TYPES)

    @staticmethod
    def completed_item(event):
        """The item a completion event names, or None; the progress row keeps no partial identity."""
        params = event.get("params") if isinstance(event, dict) and isinstance(event.get("params"), dict) else {}
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        if isinstance(item.get("id"), str) and item["id"]:
            return {"id": item["id"], "type": item.get("type"), "status": item.get("status")}
        return None


class ClaudeStream:
    """Normalized Claude Code CLI events. The raw line is kept beside every normalized field."""

    identity = "claude-code-cli"
    transport = "claude_cli"

    @staticmethod
    def shape(event) -> str | None:
        if not isinstance(event, dict):
            return "event is not an object"
        if event.get("provider") != ClaudeStream.identity:
            return "event is not a claude-code-cli event"
        if not isinstance(event.get("type"), str) or not event["type"]:
            return "normalized type is not text"
        if not isinstance(event.get("raw_type"), str) or not event["raw_type"]:
            return "provider type is not text"
        if event["type"] == "malformed":
            return str(event.get("defect") or "unparsable provider line")
        return None

    @staticmethod
    def is_progress(event) -> bool:
        return isinstance(event, dict) and event.get("type") in CLAUDE_PROGRESS

    @staticmethod
    def occurrence(event) -> str | None:
        """Claude's documented stream lines carry no wall-clock field; absence stays absence."""
        if not isinstance(event, dict):
            return None
        return epoch_millis(event.get("occurred_at_ms"))

    @staticmethod
    def event_id(event: dict, receipt_ref: str) -> str:
        label = ClaudeStream.label(event)
        identifier = event.get("id") if isinstance(event, dict) else None
        if type(identifier) is str and identifier:
            return f"{label}:{identifier}:{event.get('status')}"
        return f"{label}:{receipt_ref}"

    @staticmethod
    def label(event) -> str:
        if not isinstance(event, dict):
            return "claude/malformed"
        raw_type = event.get("raw_type")
        subtype = event.get("subtype")
        name = str(raw_type) if isinstance(raw_type, str) and raw_type else "malformed"
        return "claude/" + name + ("/" + str(subtype) if isinstance(subtype, str) and subtype else "")

    @staticmethod
    def item_type(event):
        value = event.get("type") if isinstance(event, dict) else None
        return value if type(value) is str and value else None

    @staticmethod
    def item_status(event):
        value = event.get("status") if isinstance(event, dict) else None
        return value if type(value) is str and value else None

    @staticmethod
    def tool_items(events) -> int:
        return sum(1 for event in events if isinstance(event, dict) and event.get("type") == "tool_completed")

    @staticmethod
    def completed_item(event):
        if isinstance(event, dict) and type(event.get("id")) is str and event["id"]:
            return {"id": event["id"], "type": event.get("type"), "status": event.get("status")}
        return None


STREAMS = {CodexStream.transport: CodexStream, ClaudeStream.transport: ClaudeStream}


def stream_for(transport: str):
    reader = STREAMS.get(transport)
    if reader is None:
        raise KeyError("No event reader for transport " + str(transport))
    return reader
