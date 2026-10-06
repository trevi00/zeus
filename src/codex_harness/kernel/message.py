"""Six-W message value types and the envelope constructor (schema `six-w.v1`, version "1.0").

Layer: kernel
Context: kernel
Owns: the shape of an inter-agent message (who/what/why/when/where/how) and its identity fields
Does not own: JSON-Schema validation (storage.adapters.message_schema), authorization of a
message (routing.domain.organization), delivery (storage.adapters.redis_bus)
Entry points: envelope, SixWMessage, SCHEMA_VERSION, RESULT_SCHEMA
Contracts: INV-MESSAGE-001

`message_id` is a fresh UUID and `when.created_at` the current time, both from injected ports; the
field set and the fixed defaults are the persisted M7 wire form and must not change.
"""

from __future__ import annotations

from typing import TypedDict

from codex_harness.kernel.ids import SYSTEM_IDS, utcnow
from codex_harness.kernel.ports import Clock, IdSource

SCHEMA_VERSION = "1.0"
RESULT_SCHEMA = "six-w.v1"


class Who(TypedDict):
    sender: str
    recipient: str
    owner: str


class What(TypedDict):
    action: str
    details: dict


class Why(TypedDict):
    objective: str
    evidence_refs: list


class When(TypedDict):
    created_at: str
    deadline: str | None
    after: list


class Where(TypedDict):
    repository: str
    revision: str
    environment: str
    allowed_paths: list


class How(TypedDict):
    constraints: list
    acceptance_criteria: list
    context_ref: str | None
    result_schema: str


SixWMessage = TypedDict("SixWMessage", {
    "schema_version": str, "message_id": str, "type": str, "correlation_id": str,
    "causation_id": str | None, "who": Who, "what": What, "why": Why, "when": When, "where": Where,
    "how": How})


def envelope(kind: str, sender: str, recipient: str, action: str, details: dict,
             correlation: str, cause: str | None = None, *, clock: Clock | None = None,
             ids: IdSource | None = None) -> SixWMessage:
    return {
        "schema_version": SCHEMA_VERSION, "message_id": str((ids or SYSTEM_IDS).uuid4()), "type": kind,
        "correlation_id": correlation, "causation_id": cause,
        "who": {"sender": sender, "recipient": recipient, "owner": recipient},
        "what": {"action": action, "details": details},
        "why": {"objective": "Improve harness reliability from verified evidence",
                "evidence_refs": details.get("evidence_refs", [])},
        "when": {"created_at": utcnow(clock), "deadline": None, "after": []},
        "where": {"repository": "codex-harness", "revision": "bootstrap",
                  "environment": "local", "allowed_paths": []},
        "how": {"constraints": [], "acceptance_criteria": ["Preserve normal behavior"],
                "context_ref": None, "result_schema": RESULT_SCHEMA},
    }
