"""Continuation binding validation: the lane-side binding an Operation claim may attach (INV-CONTINUATION-001).

Layer: domain
Context: coordination
Owns: `validate_binding` and the names it needs (M7 `domain/continuation.py`, moved ahead in S5 verbatim)
Does not own: the routing table, intent lifecycle and projection (S6 completes the module)
Entry points: validate_binding, ContinuationRefused, refuse, BINDING_SCHEMA, ADMITTING_ROUTES
Contracts: INV-CONTINUATION-001

Partial move: S6 completes the module. Moved names: ContinuationRefused, refuse, BINDING_SCHEMA, TOKEN,
SHA256, REVISION, EVIDENCE_REPAIR, CORRECTION, REQUALIFICATION, SUCCESSOR_ROUTES, ADMITTING_ROUTES,
validate_binding.
"""
from __future__ import annotations

import re

from codex_harness.kernel.errors import ContractError

BINDING_SCHEMA = "urn:zeus:continuation-binding:1"

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")

EVIDENCE_REPAIR = "evidence_repair"
CORRECTION = "correction"
# The owner-authorized re-derivation of an accepted change on a NEWER main after its delivery was
# withdrawn as stale (`Continuation.requalify_delivery`). It admits a fresh Fleet operation like a
# successor route, but it is deliberately NOT a successor route: it answers no failure, so it never
# counts against `max_corrections`, the two-strike research trigger or a capacity grant.
REQUALIFICATION = "requalification"
SUCCESSOR_ROUTES = frozenset({EVIDENCE_REPAIR, CORRECTION})
# Routes whose intent admits a new Fleet operation with its own lane binding (publish -> admit).
ADMITTING_ROUTES = SUCCESSOR_ROUTES | {REQUALIFICATION}


class ContinuationRefused(ContractError):
    """A refusal with a fixed reason code and the named owner who must act next."""

    def __init__(self, reason_code: str, owner: str = "operator", field: str | None = None):
        super().__init__("continuation refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.owner, self.field = reason_code, owner, field


def refuse(condition, reason_code: str, owner: str = "operator", field: str | None = None) -> None:
    if not condition:
        raise ContinuationRefused(reason_code, owner, field)


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
