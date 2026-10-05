"""S11 RU-1: behavioural nodes for the two desk routes' gates and for the decision reconciliation block.

Expected results (sources, none derived from the code under test):
- The desk gates are the ones `entry/http/desk.py`'s module docstring documents and the accepted S8 ported tests
  (`tests/ported/test_frontdesk_http.py`) fix for `POST /api/desk/sessions`: a foreign Host is 403 "Forbidden host";
  a missing/foreign Origin is 403 origin_refused, a non-JSON Content-Type 415 content_type_refused, a missing/wrong
  X-Zeus-Desk header 403 desk_header_required, a missing length (chunked) 411 content_length_required, an
  oversized body 413 body_too_large; none of them writes. The same gates must hold for `POST /api/desk/messages`
  and the Host gate for `GET /api/desk/session/<id>` (the ported tests send those gates only to other routes).
- A review decision whose run raises ReconciliationRequired is blocked, not retried (INV-OBSERVATION-001; task spec
  s11-ru1: decision `blocked` / `reconciliation_required`, no lease, the reconciliation notice, the critical audit
  row; the SOURCE case `reconciliation_required_review_lead` of effects.decision_unit records the same outcome:
  decisions_pending blocked, one events row, one execution notice, one outbox `execution.notice`, one audit row).
"""
# ruff: noqa: F811  (an imported fixture is redefined by the test argument that requests it)
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from m7_coordination import organization  # noqa: E402
from m7_executor import Executor, ReconciliationRequired  # noqa: E402
from m7_executor import Service as Harness  # noqa: E402
from test_frontdesk_http import (  # noqa: E402,F401  (fixtures and request helpers of the ported desk suite)
    CUSTOM_HEADER,
    SCHEMA,
    desk_server,
    message_body,
    open_session,
    session_body,
    snapshot,
)
from test_frontdesk_http import request as send  # noqa: E402

from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

MESSAGES, SESSION = "/api/desk/messages", "/api/desk/session/"


def queued(desk, session_id):
    return desk.session(session_id)["session"]["request_count"]


def test_messages_route_refuses_a_forbidden_host_before_anything_else(desk_server):
    server, desk = desk_server
    session_id = open_session(server)
    status, _, raw, _ = send(server, "POST", MESSAGES, message_body(session_id), host="example.com")
    assert status == 403 and raw == b"Forbidden host"
    assert queued(desk, session_id) == 0


def test_session_read_route_refuses_a_forbidden_host(desk_server):
    server, _ = desk_server
    session_id = open_session(server)
    status, _, raw, _ = send(server, "GET", SESSION + session_id, host="example.com")
    assert status == 403 and raw == b"Forbidden host"
    assert send(server, "GET", SESSION + session_id)[0] == 200  # the same read with the loopback Host is served


@pytest.mark.parametrize("headers, expected, code", [
    ({"Origin": None}, 403, "origin_refused"),
    ({"Origin": "null"}, 403, "origin_refused"),
    ({"Origin": "http://evil.example"}, 403, "origin_refused"),
    ({"Origin": "https://127.0.0.1:1"}, 403, "origin_refused"),
    ({"Content-Type": "text/plain"}, 415, "content_type_refused"),
    ({"Content-Type": "application/x-www-form-urlencoded"}, 415, "content_type_refused"),
    ({CUSTOM_HEADER: None}, 403, "desk_header_required"),
    ({CUSTOM_HEADER: "0"}, 403, "desk_header_required"),
])
def test_messages_route_requires_local_intent(desk_server, headers, expected, code):
    server, desk = desk_server
    session_id = open_session(server)
    status, document, _, response_headers = send(server, "POST", MESSAGES, message_body(session_id), headers=headers)
    assert (status, document) == (expected, {"schema": SCHEMA, "error": code})
    assert "Access-Control-Allow-Origin" not in response_headers
    assert queued(desk, session_id) == 0


def test_messages_route_refuses_a_missing_or_oversized_length_before_the_body(desk_server):
    server, desk = desk_server
    session_id = open_session(server)
    payload = json.dumps(message_body(session_id)).encode("utf-8")
    status, document, _, _ = send(server, "POST", MESSAGES, raw_body=payload,
                                  headers={"Content-Length": None, "Transfer-Encoding": "chunked"})
    assert (status, document) == (411, {"schema": SCHEMA, "error": "content_length_required"})
    oversized = json.dumps(message_body(session_id, text="x" * 40000)).encode("utf-8")
    status, document, _, _ = send(server, "POST", MESSAGES, raw_body=oversized)
    assert (status, document) == (413, {"schema": SCHEMA, "error": "body_too_large"})
    assert queued(desk, session_id) == 0


def test_a_run_that_needs_reconciliation_blocks_the_review_decision_without_a_lease(tmp_path, monkeypatch):
    store = MemoryStore()
    service = Harness(store, organization())
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *a: {}, review_workspace=lambda *a: str(tmp_path),
                          _git=lambda *a, **k: "" if a[0] == "status" else "revision")
    executor = Executor(service, git, FileArtifacts(tmp_path / "artifacts"))
    candidate = {"revision": "revision", "base": "base", "tree": "tree", "author": "worker:implementation"}
    data = {"candidate": candidate, "source_actor": "worker:implementation", "occurrence_id": "occurrence",
            "source_task_id": "task", "evidence_ref": "fixture:error"}
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement", {}, "correlation")
    with store.transaction() as tx:
        tx.put("decisions_pending", "decision", {"id": "decision", "actor": "lead:improvement", "phase": "review_lead",
               "input": data, "message": message, "status": "pending", "attempt": 0})

    def run(*args, **kwargs):  # a previous attempt ran the provider and its outcome was never recorded
        raise ReconciliationRequired("decision", [{"record_id": "record"}])

    monkeypatch.setattr(executor, "_run", run)
    executor.decide_one("lead:improvement")
    with store.transaction() as tx:
        row = tx.get("decisions_pending", "decision")
        assert (row["status"], row["error"]) == ("blocked", "reconciliation_required")
        assert row["lease_until"] is None and row["lease_owner"] is None
        assert [r["type"] for r in tx.scan("events")] == ["execution.reconciliation_required"]
        assert len(tx.scan("execution_notices")) == 1
        assert [r["message"]["type"] for r in tx.scan("outbox")] == ["execution.notice"]
        audit = tx.scan("observation_audit")
        assert len(audit) == 1
        assert audit[0]["reason_code"] == "reconciliation_required" and audit[0]["severity"] == "critical"
        assert not tx.scan("releases") and not tx.scan("release_queue")
