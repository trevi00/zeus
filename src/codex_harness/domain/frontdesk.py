"""Local front-door conversation definitions and bounds (local-operations-desk-001, part B).

Pure policy over dictionaries: identity grammar, input bounds, the durable request lifecycle and
the safe wire projections. Nothing here touches a store, a process, git or a provider, and no
value ever reaches an error message; only the fixed reason code and at most a field name do.

A stored model answer is unverified conversation context. It is never ontology, an approval, a
specification or an operation manifest, and this module never promotes it to one.
"""
from __future__ import annotations

import re

from codex_harness.domain.model import ContractError

SCHEMA = "urn:zeus:desk:1"
CONSULT, REQUEST = "consult", "request"
INTENTS = (CONSULT, REQUEST)

# Durable lifecycle. `dispatching` is the owner claim taken before any external work exists.
QUEUED, DISPATCHING = "queued", "dispatching"
ANSWERED, NEEDS_SPEC = "answered", "needs_spec"
FAILED, NEEDS_RECONCILIATION = "failed", "needs_reconciliation"
TERMINAL = frozenset({ANSWERED, NEEDS_SPEC, FAILED, NEEDS_RECONCILIATION})
OPEN = frozenset({QUEUED, DISPATCHING})
# The successful result of each intent: a consultation is answered, a request is an accepted
# proposal that still needs an owner-fixed specification. Neither is a dispatched implementation.
SUCCESS_STATE = {CONSULT: ANSWERED, REQUEST: NEEDS_SPEC}

TEXT_MIN, TEXT_MAX = 1, 6000
TITLE_MAX = 200
MAX_BODY_BYTES = 32768
MAX_SESSIONS = 50
MAX_REQUESTS_PER_SESSION = 100
PRIOR_TURNS = 10
PRIOR_CHARS = 24000
ANSWER_MAX = 20000
OBJECTIVE_MAX = 2000
LIST_ITEMS, LIST_ITEM_MAX = 20, 500

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
# Control characters are refused rather than stripped: the stored user text is exactly what was
# submitted, and the digest of the submission is what a replay is compared against.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

ANSWER_AUTHORITY = ("model_answer; unverified conversation context, not an approval, "
                    "specification or operation manifest")


class DeskRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("desk refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def safe_code(reason) -> str:
    """Only a fixed code leaves this module; anything else becomes `unknown`."""
    if not isinstance(reason, str) or SAFE_CODE.fullmatch(reason) is None:
        return "unknown"
    return reason


def identifier(value, field: str) -> str:
    """A client-generated UUID in its canonical lowercase spelling; nothing else is an identity."""
    if type(value) is not str or UUID.fullmatch(value) is None:
        raise DeskRefused("invalid_id", field)
    return value


def revision(value, field: str = "base_revision") -> str:
    if type(value) is not str or REVISION.fullmatch(value) is None:
        raise DeskRefused("invalid_revision", field)
    return value


def _plain(value, field: str, maximum: int, minimum: int = 1) -> str:
    if type(value) is not str:
        raise DeskRefused("invalid_text", field)
    if CONTROL.search(value) is not None:
        raise DeskRefused("invalid_text", field)
    text = value.strip()
    if not (minimum <= len(text) <= maximum):
        raise DeskRefused("text_out_of_bounds", field)
    return text


def title(value) -> str:
    return _plain(value, "title", TITLE_MAX)


def text(value) -> str:
    stripped = _plain(value, "text", TEXT_MAX, TEXT_MIN)
    return stripped


def intent(value) -> str:
    if type(value) is not str or value not in INTENTS:
        raise DeskRefused("invalid_intent", "intent")
    return value


def session_document(document) -> dict:
    """POST /api/desk/sessions body: exactly `session_id` and `title`."""
    if not isinstance(document, dict) or set(document) != {"session_id", "title"}:
        raise DeskRefused("invalid_body", "root")
    return {"session_id": identifier(document["session_id"], "session_id"), "title": title(document["title"])}


def message_document(document) -> dict:
    """POST /api/desk/messages body: exactly the four conversation fields."""
    expected = {"session_id", "request_id", "intent", "text"}
    if not isinstance(document, dict) or set(document) != expected:
        raise DeskRefused("invalid_body", "root")
    return {"session_id": identifier(document["session_id"], "session_id"),
            "request_id": identifier(document["request_id"], "request_id"),
            "intent": intent(document["intent"]), "text": text(document["text"])}


def new_session(session_id: str, session_title: str, now: str) -> dict:
    return {"id": session_id, "title": session_title, "request_count": 0,
            "created_at": now, "updated_at": now}


def new_request(submission: dict, base_revision: str, sequence: int, correlation_id: str,
                message_id: str, now: str) -> dict:
    """The durable request row. The user text is stored as submitted; it is user data in PG, never
    operational log content."""
    return {"id": submission["request_id"], "session_id": submission["session_id"],
            "intent": submission["intent"], "text": submission["text"],
            "originator": "local_user", "sequence": sequence,
            "status": QUEUED, "reason_code": None, "base_revision": base_revision,
            "correlation_id": correlation_id, "message_id": message_id, "task_id": None,
            "owner_token": None, "answer": None, "execution_ref": None,
            "created_at": now, "updated_at": now, "dispatched_at": None, "finished_at": None}


def submission_binding(row: dict) -> dict:
    """What an identical resubmission must repeat exactly; anything else is a refused change."""
    return {"session_id": row["session_id"], "intent": row["intent"], "text": row["text"]}


def bounded_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DeskRefused("invalid_answer", field)
    out = []
    for item in value[:LIST_ITEMS]:
        if type(item) is not str:
            raise DeskRefused("invalid_answer", field)
        cleaned = CONTROL.sub(" ", item).strip()[:LIST_ITEM_MAX]
        if cleaned:
            out.append(cleaned)
    return out


def validate_answer(document) -> dict:
    """Bound the model's fixed output JSON in the consumer as well as in the request schema.

    An over-long or malformed answer is refused here, before it is stored; a missing optional
    objective stays None. The result is conversation content, never authority.
    """
    if not isinstance(document, dict):
        raise DeskRefused("invalid_answer", "root")
    body = document.get("answer")
    if type(body) is not str:
        raise DeskRefused("invalid_answer", "answer")
    body = CONTROL.sub(" ", body).strip()
    if not body:
        raise DeskRefused("invalid_answer", "answer")
    objective = document.get("objective")
    if objective is not None:
        if type(objective) is not str:
            raise DeskRefused("invalid_answer", "objective")
        objective = CONTROL.sub(" ", objective).strip()[:OBJECTIVE_MAX] or None
    return {"answer": body[:ANSWER_MAX],
            "objective": objective,
            "acceptance_criteria": bounded_list(document.get("acceptance_criteria"), "acceptance_criteria"),
            "questions": bounded_list(document.get("questions"), "questions"),
            "authority": ANSWER_AUTHORITY}


def prior_turns(rows: list[dict]) -> dict:
    """The last completed turns of one session as bounded model evidence.

    Only terminal turns that actually carry an answer are context. The newest turns are kept; the
    number dropped for the turn and character bounds is reported rather than hidden.
    """
    completed = [row for row in rows if row["status"] in {ANSWERED, NEEDS_SPEC} and isinstance(row.get("answer"), dict)]
    completed.sort(key=lambda row: (row["sequence"], row["id"]))
    omitted = max(0, len(completed) - PRIOR_TURNS)
    selected, used = [], 0
    for row in reversed(completed[-PRIOR_TURNS:]):
        turn = {"request_id": row["id"], "intent": row["intent"], "status": row["status"],
                "user_text": row["text"], "answer": row["answer"]["answer"]}
        size = len(turn["user_text"]) + len(turn["answer"])
        if used + size > PRIOR_CHARS:
            omitted += 1
            continue
        used += size
        selected.append(turn)
    selected.reverse()
    return {"turns": selected, "omitted_turns": omitted, "characters": used,
            "bounds": {"max_turns": PRIOR_TURNS, "max_characters": PRIOR_CHARS}}


def session_view(row: dict) -> dict:
    return {"session_id": row["id"], "title": row["title"], "request_count": row["request_count"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def request_view(row: dict) -> dict:
    """The wire projection of one turn: identities, state, the user's own text and the bounded
    answer with its provenance. No owner token, no message body, no raw error."""
    answer = row.get("answer")
    return {"request_id": row["id"], "session_id": row["session_id"], "intent": row["intent"],
            "text": row["text"], "originator": row.get("originator", "local_user"),
            "status": row["status"], "reason_code": safe_code(row["reason_code"]) if row.get("reason_code") else None,
            "sequence": row["sequence"],
            "answer": {k: answer[k] for k in ("answer", "objective", "acceptance_criteria", "questions", "authority")}
            if isinstance(answer, dict) else None,
            "provenance": {"base_revision": row.get("base_revision"), "task_id": row.get("task_id"),
                           "execution_ref": row.get("execution_ref"),
                           "correlation_id": row.get("correlation_id")},
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "dispatched_at": row.get("dispatched_at"), "finished_at": row.get("finished_at")}


def sessions_projection(rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda row: (row["updated_at"], row["id"]), reverse=True)
    return {"schema": SCHEMA, "sessions": [session_view(row) for row in ordered[:MAX_SESSIONS]],
            "truncated": len(ordered) > MAX_SESSIONS}


def session_projection(session: dict, rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda row: (row["sequence"], row["id"]))
    return {"schema": SCHEMA, "session": session_view(session),
            "requests": [request_view(row) for row in ordered],
            "bounds": {"max_requests": MAX_REQUESTS_PER_SESSION}}


__all__ = ["ANSWERED", "CONSULT", "DISPATCHING", "FAILED", "INTENTS", "MAX_BODY_BYTES",
           "MAX_REQUESTS_PER_SESSION", "MAX_SESSIONS", "NEEDS_RECONCILIATION", "NEEDS_SPEC", "OPEN",
           "QUEUED", "REQUEST", "SCHEMA", "SUCCESS_STATE", "TERMINAL", "DeskRefused", "identifier",
           "intent", "message_document", "new_request", "new_session", "prior_turns",
           "request_view", "revision", "safe_code", "session_document", "session_projection",
           "session_view", "sessions_projection", "submission_binding", "text", "title",
           "validate_answer"]
