"""The bounded attributes of one refused viewer or desk HTTP request (S11 XC-2b B2, TQ-XCUT-PLAN B2).

Layer: adapters
Context: observation
Owns: `refusal_attributes`, the (route, status, code) of a refusal read from the request path and the response the
    handler already wrote, and `emit_refusal`, the one non-blocking emit of `operations.http_request_refused`
Does not own: the handler that serves the routes (`observation.adapters.viewer_http`), the desk error codes
    (`entry.http.desk`, read here only as the strings the response body carries), the observer (injected by composition)
Entry points: refusal_attributes, emit_refusal, ROUTES, CODES
Contracts: INV-OBSERVATION-001, OBSERVABILITY-COVERAGE-20261002

Only closed enums leave this module: the route is one of the fixed viewer/desk routes or `other` (a client-chosen path is
never copied), the code is a fixed label, the status is the HTTP status. No request body, header value or client address
is read. A successful request, and a `/ready` answer (a probe reporting state, not a refusal), emit nothing.
"""
from __future__ import annotations

import json

ROUTES = ("/", "/legacy", "/assets", "/api/status", "/health", "/ready", "/api/desk", "/api/desk/session",
          "/api/desk/sessions", "/api/desk/messages")
SESSION_PREFIX = "/api/desk/session/"
# The desk's own refusal codes (`entry.http.desk.check_intent` / `read_body`) as the closed `code` labels.
DESK_CODES = {"origin_refused": "origin", "desk_header_required": "desk_header", "content_type_refused": "content_type",
              "content_length_required": "content_length", "body_too_large": "body_too_large",
              "body_unreadable": "body_unreadable", "body_incomplete": "body_unreadable", "invalid_json": "invalid_json",
              "invalid_body": "invalid_body", "desk_unavailable": "desk_unavailable"}
CODES = ("host", "origin", "desk_header", "content_type", "content_length", "body_too_large", "body_unreadable",
         "invalid_json", "invalid_body", "desk_refused", "desk_unavailable", "method_not_allowed", "not_found",
         "snapshot_unavailable", "other")


def _route(path: str) -> str:
    if path in ROUTES:
        return path
    if path.startswith("/assets/"):
        return "/assets"
    if path.startswith(SESSION_PREFIX):
        return "/api/desk/session"
    return "other"


def _error(body: bytes):
    try:
        document = json.loads(body)
    except (ValueError, TypeError):
        return None
    value = document.get("error") if isinstance(document, dict) else None
    return value if isinstance(value, str) else None


def refusal_attributes(path: str, status: int, body: bytes):
    """`{route, status, code}` for a refusal response, or None when it is not one (below 400, or `/ready`)."""
    route = _route(path.split("?", 1)[0])
    if status < 400 or route == "/ready":
        return None
    error = _error(body)
    if error is not None:
        if error in DESK_CODES:
            code = DESK_CODES[error]
        elif error == "snapshot_unavailable":
            code = "snapshot_unavailable"
        else:
            code = "desk_refused" if route.startswith("/api/desk") else "other"
    elif status == 403:
        code = "host"
    elif status == 404:
        code = "not_found"
    elif status == 405:
        code = "method_not_allowed"
    else:
        code = "other"
    return {"route": route, "status": status, "code": code}


def emit_refusal(observer, path: str, status: int, body: bytes) -> None:
    """Never raises and never changes the response: an observer that fails drops the event (diagnostic `emit`)."""
    try:
        attributes = refusal_attributes(path, status, body)
        if attributes is not None:
            observer.emit("operations.http_request_refused", "blocked", attributes=attributes)
    except Exception:  # noqa: BLE001 - the diagnostic path must not turn a refusal into a different failure
        pass
