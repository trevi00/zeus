"""The fixed local desk HTTP contract, mounted into the read-only monitoring handler.

Opt-in only: `handler(snapshot_path)` without an injected desk service keeps its exact read-only
behaviour (unknown GET 404, every POST 405). With a desk service the four desk routes exist and
every state-changing request must prove local intent, following the OWASP CSRF guidance consulted
for this design: an exact `Origin` match against the already-required loopback `Host`, a
non-simple `Content-Type: application/json`, a custom `X-Zeus-Desk: 1` header and one bounded
`Content-Length`. Loopback alone is not intent, and none of this is multi-user authentication or
remote-safe exposure: the local OS user and its processes are the trust boundary.

Responses carry the fixed `urn:zeus:desk:1` schema and fixed error codes only. No request body,
header value or exception text is ever echoed back.
"""
from __future__ import annotations

import json

from codex_harness.domain.frontdesk import (
    MAX_BODY_BYTES,
    SCHEMA,
    DeskRefused,
    request_view,
    session_view,
)

JSON = "application/json; charset=utf-8"
READ_TIMEOUT_SECONDS = 5
CUSTOM_HEADER, CUSTOM_VALUE = "X-Zeus-Desk", "1"
CONTENT_TYPES = {"application/json", "application/json; charset=utf-8", "application/json;charset=utf-8"}
SESSION_PREFIX = "/api/desk/session/"
ROUTES_POST = {"/api/desk/sessions", "/api/desk/messages"}
# Reason codes that name a conflicting durable state rather than invalid input.
CONFLICT_CODES = {"session_conflict", "request_conflict", "session_busy", "session_full"}


def error(code: str) -> bytes:
    return json.dumps({"schema": SCHEMA, "error": code}, ensure_ascii=False).encode("utf-8")


def payload(document) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def status_for(exc: DeskRefused) -> int:
    """409 for a conflicting durable record, 404 for an unknown session, 400 for everything else."""
    if exc.reason_code in CONFLICT_CODES:
        return 409
    if exc.reason_code in {"session_unknown", "request_unknown"}:
        return 404
    return 400


def check_intent(handler, authority: str) -> tuple[int, str] | None:
    """Every POST gate except the body itself; returns (status, code) for a refusal or None."""
    headers = handler.headers
    origin = headers.get("Origin")
    if origin is None or origin != "http://" + authority:
        # Missing, null and foreign origins are all refused; there is no CORS grant anywhere here.
        return 403, "origin_refused"
    content_type = (headers.get("Content-Type") or "").strip().lower()
    if content_type not in CONTENT_TYPES:
        return 415, "content_type_refused"
    if (headers.get(CUSTOM_HEADER) or "").strip() != CUSTOM_VALUE:
        return 403, "desk_header_required"
    if headers.get("Transfer-Encoding") is not None:
        return 411, "content_length_required"
    raw = headers.get_all("Content-Length") or []
    if len(raw) != 1:
        return 411, "content_length_required"
    try:
        length = int(str(raw[0]).strip())
    except ValueError:
        return 411, "content_length_required"
    if length < 0:
        return 411, "content_length_required"
    if length > MAX_BODY_BYTES:
        return 413, "body_too_large"
    return None


def read_body(handler) -> tuple[dict | None, tuple[int, str] | None]:
    length = int(handler.headers.get("Content-Length"))
    try:
        raw = handler.rfile.read(length)
    except OSError:
        return None, (400, "body_unreadable")
    if len(raw) != length:
        return None, (400, "body_incomplete")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, (400, "invalid_json")
    if not isinstance(document, dict):
        return None, (400, "invalid_body")
    return document, None


def handle_get(desk, path: str):
    """(status, body) for a desk GET route, or None when this path is not a desk route."""
    if path == "/api/desk":
        return _guarded(lambda: (200, payload(desk.sessions())))
    if path.startswith(SESSION_PREFIX):
        session_id = path[len(SESSION_PREFIX):]
        return _guarded(lambda: (200, payload(desk.session(session_id))))
    return None


def handle_post(desk, path: str, document: dict):
    if path == "/api/desk/sessions":
        def run():
            created = desk.create_session(document)
            return (200 if created["cached"] else 201,
                    payload({"schema": SCHEMA, "session": session_view(created["session"]),
                             "replayed": created["cached"]}))
        return _guarded(run)

    def run():
        accepted = desk.submit(document)
        return (200 if accepted["cached"] else 202,
                payload({"schema": SCHEMA, "request": request_view(accepted["request"]),
                         "replayed": accepted["cached"]}))
    return _guarded(run)


def _guarded(call):
    """Fixed codes only: a refusal names its reason, anything else is an unavailable desk (503).

    A store that cannot be reached is 503 with no local fallback and no stored answer; the raw
    exception never leaves this process.
    """
    try:
        return call()
    except DeskRefused as exc:
        return status_for(exc), error(exc.reason_code)
    except Exception:
        return 503, error("desk_unavailable")


__all__ = ["CUSTOM_HEADER", "CUSTOM_VALUE", "JSON", "READ_TIMEOUT_SECONDS", "ROUTES_POST",
           "SESSION_PREFIX", "check_intent", "error", "handle_get", "handle_post", "read_body",
           "status_for"]
