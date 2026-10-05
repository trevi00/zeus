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


# ---- B3: credential-pattern redaction of persisted provider-stream artifacts ------------------------------------------------
# A GitHub-token-shaped string, assembled at run time so no scanner sees a literal token in the repository.
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def stream_document(text):
    """The shape RunTask persists as `execution:<key>`: provider events with assistant text and tool results."""
    return {"thread_id": "t1", "events": [
        {"method": "claude/assistant", "params": {"text": text}},
        {"method": "claude/tool_completed", "params": {"tool_result": "output: " + text}}],
        "answer": {"summary": "done"}, "stderr_tail": [text]}


def production_artifacts(tmp_path):
    """RunTask's artifact store exactly as the production composition wires it (`composition.operation.Executor`)."""
    from types import SimpleNamespace

    from codex_harness import composition
    from codex_harness.composition import operation
    from codex_harness.routing.adapters.organization_source import packaged_organization
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    from codex_harness.storage.adapters.memory_store import MemoryStore

    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    git = SimpleNamespace(_git=lambda *a, **k: "revision", repository=tmp_path)
    raw = FileArtifacts(str(tmp_path / "artifacts"))
    return operation.Executor(service, git, raw, knowledge=None).run_task.artifacts, raw


def stored_bytes(raw, receipt):
    return (raw.root / (receipt["ref"][7:] + ".txt")).read_bytes()


@pytest.mark.parametrize("source", ["execution:task-1", "runtime-event:task-1"])
def test_a_credential_in_a_provider_stream_artifact_is_redacted_before_it_is_written(tmp_path, source):
    import hashlib

    from codex_harness.execution.adapters.execution_output import evidence_json

    artifacts, raw = production_artifacts(tmp_path)
    receipt = artifacts.put(evidence_json(stream_document("the key is " + TOKEN)), source)
    data = stored_bytes(raw, receipt)
    assert TOKEN.encode() not in data and b"[REDACTED token]" in data
    assert TOKEN not in raw.read(receipt["ref"], 0, 32000)  # what `zeus artifact` serves
    assert TOKEN not in json.dumps(raw.search(receipt["ref"], "ghp_"))  # and its --search
    assert receipt["redactions"] >= 1 and raw.inspect(receipt["ref"])["metadata"]["redactions"] == receipt["redactions"]
    assert receipt["ref"] == "sha256:" + hashlib.sha256(data).hexdigest() and receipt["bytes"] == len(data)
    json.loads(data)  # the artifact is still the (redacted) JSON document


def test_a_stream_without_a_credential_is_stored_byte_identically_with_a_zero_count(tmp_path):
    from codex_harness.execution.adapters.execution_output import evidence_json

    artifacts, raw = production_artifacts(tmp_path)
    body = evidence_json(stream_document("구현을 마쳤습니다 (an ordinary assistant message)"))
    receipt = artifacts.put(body, "execution:task-2")
    assert stored_bytes(raw, receipt) == body.encode("utf-8") and receipt["redactions"] == 0
    assert raw.put(body, "execution:task-2")["ref"] == receipt["ref"]  # the same bytes as an unwrapped store


def test_only_provider_stream_artifacts_are_redacted(tmp_path):
    artifacts, raw = production_artifacts(tmp_path)
    body = json.dumps({"note": TOKEN})
    receipt = artifacts.put(body, "git-rebase")
    assert stored_bytes(raw, receipt) == body.encode() and "redactions" not in receipt


# ---- B4: `spec_digest` in the observation execution identity ----------------------------------------------------------------
def task_lease(task_id, details):
    message = {"what": {"action": "implement", "details": details}}
    return {"id": task_id, "_bucket": "tasks", "generation": 1, "attempt": 1, "agent": "worker:implementation",
            "message": message}


def bound(ticket_id, content_hash):
    return {"zeus_ticket": {"id": ticket_id, "revision": 1, "content_hash": content_hash}}


def test_two_concurrent_tasks_with_different_specs_record_different_digests_correlated_to_their_own_task(tmp_path):
    from threading import Barrier

    from codex_harness.kernel.ids import digest
    from codex_harness.observation.adapters.observation_schema import validate_observation

    spec_a, spec_b = digest({"objective": "add a slug helper"}), digest({"objective": "retire the legacy desk"})
    observer = real_observer()
    leases = {"task-a": task_lease("task-a", {"plan": {"candidate": bound("T-1", spec_a)}}),
              "task-b": task_lease("task-b", bound("T-2", spec_b))}
    start = Barrier(2)

    def run(task_id):
        start.wait()
        for _ in range(25):
            observer.emit("development.progress_recorded", "observed", execution=observer.for_lease(leases[task_id]),
                          attributes={"progress_sequence": 1, "method": "m", "item_type": "i", "item_status": "s",
                                      "receipt_ref": "sha256:" + "0" * 64, "malformed": False, "defect": None})

    threads = [Thread(target=run, args=(task_id,)) for task_id in leases]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    records = [r for r in observer.spool.records() if r["event_type"] == "development.progress_recorded"]
    assert len(records) == 50
    seen = {(r["execution"]["task_id"], r["execution"]["spec_digest"]) for r in records}
    assert seen == {("task-a", spec_a), ("task-b", spec_b)} and spec_a != spec_b
    for record in records:
        validate_observation({k: v for k, v in record.items() if k not in {"payload_hash", "authority"}})


def test_a_task_without_a_spec_and_every_system_identity_record_unknown(tmp_path):
    observer = real_observer()
    plain = observer.for_lease(task_lease("task-c", {"plan": {"objective": "no ticket"}}))
    two_specs = observer.for_lease(task_lease("task-d", {"a": bound("T-1", "sha256:" + "1" * 64),
                                                         "b": bound("T-2", "sha256:" + "2" * 64)}))
    assert plain["spec_digest"] == "unknown" and two_specs["spec_digest"] == "unknown"
    assert observer.system()["spec_digest"] == "unknown"
    assert observer.for_lease({"id": "task-e", "_bucket": "tasks", "generation": 1, "attempt": 1, "agent": "worker:implementation"})["spec_digest"] == "unknown"


def test_the_spec_digest_is_fixed_when_the_identity_is_built_not_read_at_emit_time():
    lease = task_lease("task-f", bound("T-3", "sha256:" + "3" * 64))
    observer = real_observer()
    identity = observer.for_lease(lease)
    lease["message"]["what"]["details"] = {}  # the live row changes afterwards
    observer.emit("development.progress_recorded", "observed", execution=identity, attributes={
        "progress_sequence": 1, "method": "m", "item_type": "i", "item_status": "s",
        "receipt_ref": "sha256:" + "0" * 64, "malformed": False, "defect": None})
    [record] = [r for r in observer.spool.records() if r["event_type"] == "development.progress_recorded"]
    assert record["execution"]["spec_digest"] == "sha256:" + "3" * 64


def test_an_event_recorded_before_spec_digest_existed_still_validates():
    from codex_harness.observation.adapters.observation_schema import validate_observation

    observer = real_observer()
    observer.emit("operations.http_request_refused", "blocked", attributes={"route": "/", "status": 404, "code": "not_found"})
    [record] = refused_events(observer)
    old = {k: v for k, v in record.items() if k not in {"payload_hash", "authority"}}
    del old["execution"]["spec_digest"]
    validate_observation(old)
