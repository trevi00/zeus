"""The local desk HTTP contract over an ACTUAL loopback server and real requests.

A real `ThreadingHTTPServer` with the production handler is started on 127.0.0.1 and driven with
`http.client`, so the Host/Origin/header/length gates are exercised by the transport itself. The
store behind it is a MemoryStore; no Codex, Claude or other provider is involved anywhere here.
"""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from uuid import uuid4

import pytest

from codex_harness.adapters.frontdesk_http import CUSTOM_HEADER
from codex_harness.adapters.monitoring_web import handler
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.frontdesk import FrontDesk
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization

REVISION = "0" * 39 + "a"
SCHEMA = "urn:zeus:desk:1"


class Unavailable:
    """An injected store outage: every transaction fails, exactly like an unreachable PostgreSQL."""

    def transaction(self):
        raise OSError("injected store outage")


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "monitoring.json"
    path.write_text(json.dumps({"sources": {}}), encoding="utf-8")
    return path


def start(snapshot_path, desk):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(snapshot_path, desk))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def desk_server(snapshot):
    service = Harness(MemoryStore(), organization())
    desk = FrontDesk(service, REVISION)
    server, thread = start(snapshot, desk)
    yield server, desk
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def readonly_server(snapshot):
    server, thread = start(snapshot, None)
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(server, method, path, body=None, headers=None, host=None, raw_body=None):
    port = server.server_port
    authority = host or f"127.0.0.1:{port}"
    connection = HTTPConnection("127.0.0.1", port, timeout=10)
    payload = raw_body if raw_body is not None else (
        json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
    sent = {"Host": authority}
    if payload is not None:
        sent.update({"Origin": "http://" + authority, "Content-Type": "application/json",
                     CUSTOM_HEADER: "1", "Content-Length": str(len(payload))})
    for key, value in (headers or {}).items():
        if value is None:
            sent.pop(key, None)
        else:
            sent[key] = value
    try:
        connection.request(method, path, body=payload, headers=sent)
        response = connection.getresponse()
        raw = response.read()
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            document = None
        return response.status, document, raw, dict(response.getheaders())
    finally:
        connection.close()


def session_body(title="로컬 세션"):
    return {"session_id": str(uuid4()), "title": title}


def open_session(server):
    body = session_body()
    status, document, _, _ = request(server, "POST", "/api/desk/sessions", body)
    assert status == 201 and document["schema"] == SCHEMA
    return body["session_id"]


def message_body(session_id, text="상태 알려줘", intent="consult", request_id=None):
    return {"session_id": session_id, "request_id": request_id or str(uuid4()),
            "intent": intent, "text": text}


# ----- the read-only handler is unchanged without an injected desk ----------------------------
def test_without_a_desk_the_handler_stays_read_only(readonly_server):
    status, _, raw, _ = request(readonly_server, "POST", "/api/desk/messages", message_body(str(uuid4())))
    assert status == 405 and raw == b"Read only"
    assert request(readonly_server, "POST", "/api/desk/sessions", session_body())[0] == 405
    assert request(readonly_server, "GET", "/api/desk")[0] == 404
    assert request(readonly_server, "GET", "/api/desk/session/" + str(uuid4()))[0] == 404
    status, document, _, _ = request(readonly_server, "GET", "/api/status")
    assert status == 200 and document == {"sources": {}}
    assert request(readonly_server, "GET", "/health")[0] == 200


def test_existing_read_only_routes_are_unchanged_with_a_desk(desk_server):
    server, _ = desk_server
    assert request(server, "GET", "/health")[1] == {"service": "harness-monitor"}
    assert request(server, "GET", "/api/status")[0] == 200
    assert request(server, "GET", "/nope")[0] == 404
    # An unrelated POST is still 405, desk or no desk.
    assert request(server, "POST", "/api/status", {"x": 1})[0] == 405


def test_forbidden_host_is_refused_for_reads_and_writes(desk_server):
    server, _ = desk_server
    assert request(server, "GET", "/api/desk", host="example.com")[0] == 403
    status, _, raw, _ = request(server, "POST", "/api/desk/sessions", session_body(), host="example.com")
    assert status == 403 and raw == b"Forbidden host"


# ----- browser authority gates -----------------------------------------------------------------
@pytest.mark.parametrize("headers, expected, code", [
    ({"Origin": None}, 403, "origin_refused"),
    ({"Origin": "null"}, 403, "origin_refused"),
    ({"Origin": "http://evil.example"}, 403, "origin_refused"),
    ({"Origin": "https://127.0.0.1:1"}, 403, "origin_refused"),
    ({"Content-Type": "text/plain"}, 415, "content_type_refused"),
    ({"Content-Type": "application/x-www-form-urlencoded"}, 415, "content_type_refused"),
    ({"Content-Type": "multipart/form-data; boundary=x"}, 415, "content_type_refused"),
    ({CUSTOM_HEADER: None}, 403, "desk_header_required"),
    ({CUSTOM_HEADER: "0"}, 403, "desk_header_required"),
])
def test_state_changing_requests_must_prove_local_intent(desk_server, headers, expected, code):
    server, desk = desk_server
    status, document, _, response_headers = request(server, "POST", "/api/desk/sessions",
                                                    session_body(), headers=headers)
    assert (status, document) == (expected, {"schema": SCHEMA, "error": code})
    assert "Access-Control-Allow-Origin" not in response_headers  # no CORS grant anywhere
    assert desk.sessions()["sessions"] == []


def test_charset_on_the_json_content_type_is_accepted(desk_server):
    server, _ = desk_server
    status, _, _, _ = request(server, "POST", "/api/desk/sessions", session_body(),
                              headers={"Content-Type": "application/json; charset=utf-8"})
    assert status == 201


def test_a_missing_or_oversized_length_is_refused_before_the_body(desk_server):
    server, desk = desk_server
    payload = json.dumps(session_body()).encode("utf-8")
    status, document, _, _ = request(server, "POST", "/api/desk/sessions", raw_body=payload,
                                     headers={"Content-Length": None, "Origin": "http://127.0.0.1:%d" % server.server_port,
                                              "Content-Type": "application/json", CUSTOM_HEADER: "1",
                                              "Transfer-Encoding": "chunked"})
    assert (status, document) == (411, {"schema": SCHEMA, "error": "content_length_required"})
    oversized = json.dumps({"session_id": str(uuid4()), "title": "x" * 40000}).encode("utf-8")
    status, document, _, _ = request(server, "POST", "/api/desk/sessions", raw_body=oversized)
    assert (status, document) == (413, {"schema": SCHEMA, "error": "body_too_large"})
    assert desk.sessions()["sessions"] == []


@pytest.mark.parametrize("raw, code", [
    (b"not json", "invalid_json"),
    (b"[1,2]", "invalid_body"),
    (b"\xff\xfe", "invalid_json"),
])
def test_unparsable_bodies_are_refused_without_echoing_them(desk_server, raw, code):
    server, _ = desk_server
    status, document, body, _ = request(server, "POST", "/api/desk/sessions", raw_body=raw)
    assert (status, document) == (400, {"schema": SCHEMA, "error": code})
    assert raw not in body


# ----- the desk routes --------------------------------------------------------------------------
def test_session_creation_returns_201_then_a_200_replay(desk_server):
    server, desk = desk_server
    body = session_body()
    status, created, _, _ = request(server, "POST", "/api/desk/sessions", body)
    assert status == 201 and created["replayed"] is False
    assert created["session"] == {"session_id": body["session_id"], "title": body["title"],
                                  "request_count": 0, "created_at": created["session"]["created_at"],
                                  "updated_at": created["session"]["updated_at"]}
    status, replay, _, _ = request(server, "POST", "/api/desk/sessions", body)
    assert status == 200 and replay["replayed"] is True
    status, conflict, _, _ = request(server, "POST", "/api/desk/sessions",
                                     {"session_id": body["session_id"], "title": "다른 제목"})
    assert (status, conflict) == (409, {"schema": SCHEMA, "error": "session_conflict"})


def test_message_submission_is_accepted_replayed_and_conflict_checked(desk_server):
    server, desk = desk_server
    session_id = open_session(server)
    body = message_body(session_id)
    status, accepted, _, _ = request(server, "POST", "/api/desk/messages", body)
    assert status == 202 and accepted["replayed"] is False
    assert accepted["request"]["status"] == "queued" and accepted["request"]["originator"] == "local_user"
    assert accepted["request"]["answer"] is None
    assert accepted["request"]["provenance"]["base_revision"] == REVISION
    status, replay, _, _ = request(server, "POST", "/api/desk/messages", body)
    assert status == 200 and replay["replayed"] is True and replay["request"] == accepted["request"]
    status, conflict, _, _ = request(server, "POST", "/api/desk/messages",
                                     {**body, "text": "다른 질문"})
    assert (status, conflict) == (409, {"schema": SCHEMA, "error": "request_conflict"})
    status, busy, _, _ = request(server, "POST", "/api/desk/messages", message_body(session_id, "두번째"))
    assert (status, busy) == (409, {"schema": SCHEMA, "error": "session_busy"})


@pytest.mark.parametrize("body, code", [
    ({"session_id": "nope", "request_id": str(uuid4()), "intent": "consult", "text": "t"}, "invalid_id"),
    ({"session_id": str(uuid4()), "request_id": str(uuid4()), "intent": "deploy", "text": "t"}, "invalid_intent"),
    ({"session_id": str(uuid4()), "request_id": str(uuid4()), "intent": "consult", "text": ""}, "text_out_of_bounds"),
    ({"session_id": str(uuid4()), "request_id": str(uuid4()), "intent": "consult", "text": "x" * 6001},
     "text_out_of_bounds"),
    ({"session_id": str(uuid4()), "request_id": str(uuid4()), "intent": "consult"}, "invalid_body"),
    ({"session_id": str(uuid4()), "request_id": str(uuid4()), "intent": "consult", "text": "t",
      "base_revision": "b" * 40}, "invalid_body"),
])
def test_invalid_submissions_are_400_with_a_fixed_code(desk_server, body, code):
    server, _ = desk_server
    status, document, _, _ = request(server, "POST", "/api/desk/messages", body)
    assert (status, document) == (400, {"schema": SCHEMA, "error": code})


def test_a_submission_to_an_unknown_session_is_404(desk_server):
    server, _ = desk_server
    status, document, _, _ = request(server, "POST", "/api/desk/messages", message_body(str(uuid4())))
    assert (status, document) == (404, {"schema": SCHEMA, "error": "session_unknown"})


def test_reading_sessions_and_one_ordered_session_history(desk_server):
    server, desk = desk_server
    session_id = open_session(server)
    request(server, "POST", "/api/desk/messages", message_body(session_id, "첫 질문"))
    status, listing, _, _ = request(server, "GET", "/api/desk")
    assert status == 200 and listing["schema"] == SCHEMA
    assert [row["session_id"] for row in listing["sessions"]] == [session_id]
    status, detail, _, _ = request(server, "GET", "/api/desk/session/" + session_id)
    assert status == 200 and detail["session"]["request_count"] == 1
    assert [row["text"] for row in detail["requests"]] == ["첫 질문"]
    assert detail["requests"][0]["status"] == "queued" and detail["requests"][0]["answer"] is None
    assert "owner_token" not in detail["requests"][0]


def test_an_answer_survives_a_reload_and_is_bound_to_its_request(desk_server):
    server, desk = desk_server
    session_id = open_session(server)
    body = message_body(session_id, "구독 사용량 설명해줘")
    request(server, "POST", "/api/desk/messages", body)
    claimed = desk.claim_next()
    desk.finalize(body["request_id"], claimed["owner_token"], status="answered",
                  answer={"answer": "구독 사용량 기록", "objective": None, "acceptance_criteria": [],
                          "questions": [], "authority": "model_answer; unverified"},
                  task_id="desk-" + body["request_id"], execution_ref="sha256:" + "c" * 64)
    status, detail, _, _ = request(server, "GET", "/api/desk/session/" + session_id)
    turn = detail["requests"][0]
    assert status == 200 and turn["request_id"] == body["request_id"] and turn["status"] == "answered"
    assert turn["answer"]["answer"] == "구독 사용량 기록"
    assert turn["provenance"]["task_id"] == "desk-" + body["request_id"]
    assert turn["provenance"]["execution_ref"] == "sha256:" + "c" * 64


def test_a_bad_session_identifier_in_the_path_is_400(desk_server):
    server, _ = desk_server
    status, document, _, _ = request(server, "GET", "/api/desk/session/not-a-uuid")
    assert (status, document) == (400, {"schema": SCHEMA, "error": "invalid_id"})
    status, document, _, _ = request(server, "GET", "/api/desk/session/" + str(uuid4()))
    assert (status, document) == (404, {"schema": SCHEMA, "error": "session_unknown"})


def test_an_unavailable_store_is_503_with_no_local_fallback(snapshot):
    desk = FrontDesk(Harness(MemoryStore(), organization()), REVISION)
    desk.store = Unavailable()  # injected outage, exactly like an unreachable PostgreSQL
    desk.service = type(desk.service)(Unavailable(), organization())
    server, thread = start(snapshot, desk)
    try:
        status, document, _, _ = request(server, "GET", "/api/desk")
        assert (status, document) == (503, {"schema": SCHEMA, "error": "desk_unavailable"})
        status, document, _, _ = request(server, "POST", "/api/desk/messages",
                                         message_body(str(uuid4())))
        assert (status, document) == (503, {"schema": SCHEMA, "error": "desk_unavailable"})
        assert request(server, "GET", "/health")[0] == 200  # the read-only routes keep working
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
