"""S11 XC-2b: TQ-XCUT-PLAN B2 (a catalogued refusal event at the HTTP boundary), B3 (credential redaction of persisted
provider-stream artifacts) and B4 (`spec_digest` in the observation execution identity).

Behavioural tests over the public boundaries (a loopback server, the artifact store and the observer); expected values
come from the owner rules in the task spec, never from the implementation.
"""

from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from codex_harness.entry.http import desk as desk_http
from codex_harness.intake.domain.frontdesk import MAX_BODY_BYTES, DeskRefused
from codex_harness.observation.adapters import viewer_http
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.application.observations import Observer
from codex_harness.observation.domain.observation import new_process_run_id

REFUSED = "operations.http_request_refused"
POST = "/api/desk/messages"
GOOD_DOCUMENT = json.dumps({"text": "hello"}).encode()
FIXED_CLOCK = lambda: "2026-10-05T00:00:00+00:00"  # noqa: E731


class MemoryDirectory:
    def read_health(self):
        return []


class FakeDesk:
    """The desk service the handler calls: accepts a message, or refuses/fails as scripted."""

    def __init__(self):
        self.fail = None

    def submit(self, document):
        if self.fail is not None:
            raise self.fail
        request = {"id": "r1", "session_id": "s1", "intent": "ask", "text": "hello", "status": "accepted",
                   "sequence": 1, "created_at": "t", "updated_at": "t"}
        return {"cached": False, "request": request}

    def sessions(self):
        return {"schema": "urn:zeus:desk:1", "sessions": []}

    def session(self, session_id):
        raise DeskRefused("session_unknown")


def real_observer():
    return CatalogCheckingObserver(Observer(None, MemorySpool(new_process_run_id()), component="viewer-test",
                                            directory=MemoryDirectory(), clock=FIXED_CLOCK))


def refused_events(observer):
    return [r for r in observer.spool.records() if r["event_type"] == REFUSED]


class Served:
    def __init__(self, tmp_path, observer, desk=None, snapshot=True):
        self.snapshot = tmp_path / "monitoring.json"
        if snapshot:
            self.snapshot.write_text('{"sources": {}}')
        wired = desk is not None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), viewer_http.handler(
            self.snapshot, desk, desk_http=desk_http if wired else None, observer=observer))
        self.server.daemon_threads = True
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_port

    def request(self, method, path, headers=None, body=None, host="default"):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"127.0.0.1:{self.port}" if host == "default" else host)
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        result = (response.status, response.read())
        connection.close()
        return result

    def post(self, headers=None, body=GOOD_DOCUMENT, path=POST, **kwargs):
        sent = {"Origin": f"http://127.0.0.1:{self.port}", "Content-Type": "application/json", "X-Zeus-Desk": "1",
                "Content-Length": str(len(body))}
        sent.update(headers or {})
        sent = {k: v for k, v in sent.items() if v is not None}
        return self.request("POST", path, sent, body, **kwargs)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def served(tmp_path):
    made = []

    def make(observer, desk=None, **kwargs):
        made.append(Served(tmp_path, observer, desk, **kwargs))
        return made[-1]

    yield make
    for item in made:
        item.close()


REFUSALS = [
    ("host", dict(host="evil.example"), 403, "host"),
    ("origin", dict(headers={"Origin": "http://evil.example"}), 403, "origin"),
    ("desk_header", dict(headers={"X-Zeus-Desk": "0"}), 403, "desk_header"),
    ("content_type", dict(headers={"Content-Type": "text/plain"}), 415, "content_type"),
    ("content_length", dict(headers={"Content-Length": None}), 411, "content_length"),
    ("too_large", dict(headers={"Content-Length": str(MAX_BODY_BYTES + 1)}), 413, "body_too_large"),
    ("invalid_json", dict(body=b"{not json"), 400, "invalid_json"),
    ("invalid_body", dict(body=b"[1]"), 400, "invalid_body"),
]


@pytest.mark.parametrize("name,kwargs,status,code", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_each_desk_refusal_class_emits_exactly_one_event_with_its_code(served, name, kwargs, status, code):
    observer = real_observer()
    server = served(observer, FakeDesk())
    assert server.post(**kwargs)[0] == status
    [event] = refused_events(observer)
    assert event["attributes"] == {"route": POST, "status": status, "code": code}
    assert event["outcome"] == "blocked" and event["execution"]["kind"] == "system"


def test_a_desk_failure_is_a_503_event_and_a_desk_refusal_is_a_400_event(served):
    observer, desk = real_observer(), FakeDesk()
    server = served(observer, desk)
    desk.fail = RuntimeError("store unreachable")
    assert server.post()[0] == 503
    desk.fail = DeskRefused("empty_text")
    assert server.post()[0] == 400
    attributes = [e["attributes"] for e in refused_events(observer)]
    assert attributes == [{"route": POST, "status": 503, "code": "desk_unavailable"},
                          {"route": POST, "status": 400, "code": "desk_refused"}]


def test_viewer_refusals_are_events_and_the_event_carries_no_request_data(served):
    observer = real_observer()
    server = served(observer, snapshot=False)
    assert server.request("GET", "/api/status")[0] == 503
    assert server.request("GET", "/nope/secret-path?token=abc")[0] == 404
    assert server.request("POST", "/api/status", {"Content-Length": "0"})[0] == 405
    assert server.request("GET", "/api/status", host="evil.example")[0] == 403
    events = refused_events(observer)
    assert [e["attributes"] for e in events] == [
        {"route": "/api/status", "status": 503, "code": "snapshot_unavailable"},
        {"route": "other", "status": 404, "code": "not_found"},
        {"route": "/api/status", "status": 405, "code": "method_not_allowed"},
        {"route": "/api/status", "status": 403, "code": "host"}]
    text = json.dumps(events)
    assert "secret-path" not in text and "token=abc" not in text and "evil.example" not in text
    assert "127.0.0.1" not in json.dumps([e["attributes"] for e in events])


def test_an_accepted_post_and_a_successful_get_emit_nothing(served):
    observer = real_observer()
    server = served(observer, FakeDesk())
    assert server.post()[0] == 202
    assert server.request("GET", "/api/status")[0] == 200
    assert server.request("GET", "/health")[0] == 200
    assert server.request("GET", "/api/desk")[0] == 200
    assert refused_events(observer) == []


def test_an_observer_that_raises_does_not_change_the_http_response(served, tmp_path):
    class Raising:
        def emit(self, *args, **kwargs):
            raise RuntimeError("observer down")

    plain = served(None, FakeDesk())
    broken = served(Raising(), FakeDesk())
    for kwargs in (dict(headers={"Origin": "http://evil.example"}), dict(body=b"{x"), dict(host="evil.example")):
        assert broken.post(**kwargs) == plain.post(**kwargs)
    assert broken.request("GET", "/missing") == plain.request("GET", "/missing")
