"""Local front door (local-operations-desk-001, part B): durable turns and the conductor handoff.

Every executor and bus here is an injected stand-in. No test in this file calls Codex, Claude or
any other provider, and an injected failure is labelled as injected: these are contract tests over
the real store, Workflow, outbox and organization, not evidence that a model ran.
"""
import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.frontdesk import (
    BUCKET_REQUESTS,
    LEAD,
    DeskRunner,
    FrontDesk,
    message_id_of,
)
from codex_harness.application.service import Harness
from codex_harness.application.workflow import ClaimGuardRefused, Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain import frontdesk as desk_domain
from codex_harness.domain.frontdesk import DeskRefused, prior_turns, validate_answer
from codex_harness.domain.model import canonical

REVISION = "0" * 39 + "a"


def service():
    return Harness(MemoryStore(), organization())


def ids(count=1):
    return [str(uuid4()) for _ in range(count)]


def opened(svc=None, title="로컬 운영 데스크"):
    svc = svc or service()
    desk = FrontDesk(svc, REVISION)
    session_id = str(uuid4())
    desk.create_session({"session_id": session_id, "title": title})
    return svc, desk, session_id


def submit(desk, session_id, text="지금 상태가 어때?", intent="consult", request_id=None):
    return desk.submit({"session_id": session_id, "request_id": request_id or str(uuid4()),
                        "intent": intent, "text": text})


ANSWER = {"answer": "구독 사용량은 기록되고 호출 수 상한은 적용되지 않습니다.", "objective": None,
          "acceptance_criteria": [], "questions": [], "execution_ref": "sha256:" + "b" * 64}


class FakeBus:
    """A stand-in transport with the RedisBus surface the outbox and the runner use."""

    def __init__(self):
        self.streams, self.published, self.acked = {}, [], []

    @staticmethod
    def validate(message):
        return validate_message(message)

    def publish(self, message):
        self.validate(message)
        entry_id = str(len(self.published) + 1)
        self.published.append(message)
        self.streams.setdefault(message["who"]["recipient"], []).append((entry_id, {"body": canonical(message)}))
        return entry_id

    def receive(self, agent, consumer, idle_ms=60000):
        rows = self.streams.get(agent) or []
        return rows[0] if rows else None

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)
        self.streams[agent] = [row for row in self.streams.get(agent, []) if row[0] != entry_id]

    @staticmethod
    def decode(fields):
        return validate_message(json.loads(fields["body"]))


class FakeExecutor:
    """Stand-in for the budgeted Codex executor: it drives the REAL claim/complete path but never
    enters a provider. `answer` is injected, and `error`/`status` are injected failures."""

    def __init__(self, svc, answer=None, status="succeeded", error=None, slots=None):
        self.svc, self.answer, self.status, self.error = svc, answer or dict(ANSWER), status, error
        self.slots = slots if slots is not None else []
        self.calls = []

    def execute_one(self, agent, expected=None):
        self.calls.append({"agent": agent, "expected": expected})
        workflow = Workflow(self.svc.store, self.svc.org)
        task = workflow.claim(agent, "desk-owner-" + uuid4().hex, expected=expected)
        if task is None:
            return None
        if self.error is not None:
            raise self.error
        if self.status != "succeeded":
            return workflow.fail(task, "injected failure", retryable=self.status == "retry")
        return workflow.complete(task, dict(self.answer), [])


def runner(svc, desk, executor, bus=None):
    bus = bus if bus is not None else FakeBus()
    return DeskRunner(svc, desk, executor, bus, Workflow(svc.store, svc.org)), bus


# ----- identity, bounds and idempotent intake ------------------------------------------------
def test_session_creation_is_idempotent_and_refuses_a_second_title():
    _, desk, session_id = opened()
    again = desk.create_session({"session_id": session_id, "title": "로컬 운영 데스크"})
    assert again["cached"] is True and again["session"]["request_count"] == 0
    with pytest.raises(DeskRefused) as refused:
        desk.create_session({"session_id": session_id, "title": "다른 제목"})
    assert refused.value.reason_code == "session_conflict"


@pytest.mark.parametrize("document, code", [
    ({"session_id": "not-a-uuid", "title": "t"}, "invalid_id"),
    ({"session_id": str(uuid4())}, "invalid_body"),
    ({"session_id": str(uuid4()), "title": "t", "extra": 1}, "invalid_body"),
    ({"session_id": str(uuid4()), "title": ""}, "text_out_of_bounds"),
    ({"session_id": str(uuid4()), "title": "x" * 201}, "text_out_of_bounds"),
])
def test_session_body_is_bounded(document, code):
    _, desk, _ = opened()
    with pytest.raises(DeskRefused) as refused:
        desk.create_session(document)
    assert refused.value.reason_code == code


@pytest.mark.parametrize("field, value, code", [
    ("intent", "implement", "invalid_intent"),
    ("text", "", "text_out_of_bounds"),
    ("text", "x" * 6001, "text_out_of_bounds"),
    ("text", "hello\x00there", "invalid_text"),
    ("request_id", "12345", "invalid_id"),
])
def test_submission_bounds_refuse_before_any_row(field, value, code):
    svc, desk, session_id = opened()
    body = {"session_id": session_id, "request_id": str(uuid4()), "intent": "consult", "text": "ok"}
    body[field] = value
    with pytest.raises(DeskRefused) as refused:
        desk.submit(body)
    assert refused.value.reason_code == code
    with svc.store.transaction() as tx:
        assert tx.scan(BUCKET_REQUESTS) == [] and tx.scan("outbox") == []


def test_submission_persists_the_turn_and_its_assignment_together():
    svc, desk, session_id = opened()
    request_id = str(uuid4())
    accepted = submit(desk, session_id, request_id=request_id)
    assert accepted["cached"] is False and accepted["request"]["status"] == "queued"
    assert accepted["request"]["originator"] == "local_user"
    assert accepted["request"]["base_revision"] == REVISION
    with svc.store.transaction() as tx:
        row = tx.get(BUCKET_REQUESTS, request_id)
        outbox = tx.get("outbox", message_id_of(request_id))
        session = tx.get("desk_sessions", session_id)
    assert row["text"] == "지금 상태가 어때?" and session["request_count"] == 1
    message = outbox["message"]
    assert outbox["sent"] is False and message["who"] == {"sender": "conductor", "recipient": LEAD, "owner": LEAD}
    assert message["what"]["action"] == "frontdesk"
    assert message["where"]["revision"] == REVISION
    # Identities only: no user text travels through the bus, the outbox or a quarantine copy.
    assert message["what"]["details"] == {"frontdesk": {
        "request_id": request_id, "session_id": session_id, "intent": "consult",
        "originator": "local_user", "base_revision": REVISION}}
    validate_message(message)
    svc.org.authorize(message)


def test_same_request_replays_and_a_changed_body_conflicts():
    svc, desk, session_id = opened()
    request_id = str(uuid4())
    first = submit(desk, session_id, request_id=request_id)
    replay = submit(desk, session_id, request_id=request_id)
    assert replay["cached"] is True and replay["request"] == first["request"]
    with pytest.raises(DeskRefused) as refused:
        submit(desk, session_id, text="다른 내용", request_id=request_id)
    assert refused.value.reason_code == "request_conflict"
    other_session = str(uuid4())
    desk.create_session({"session_id": other_session, "title": "두번째"})
    with pytest.raises(DeskRefused) as conflict:
        submit(desk, other_session, request_id=request_id)
    assert conflict.value.reason_code == "request_conflict"
    with svc.store.transaction() as tx:
        assert len(tx.scan(BUCKET_REQUESTS)) == 1


def test_concurrent_identical_submissions_create_exactly_one_turn():
    svc, desk, session_id = opened()
    request_id, results, errors = str(uuid4()), [], []

    def call():
        try:
            results.append(desk.submit({"session_id": session_id, "request_id": request_id,
                                        "intent": "consult", "text": "동시 제출"}))
        except Exception as exc:  # recorded, never swallowed
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and len(results) == 6
    assert sum(1 for row in results if row["cached"] is False) == 1
    with svc.store.transaction() as tx:
        assert len(tx.scan(BUCKET_REQUESTS)) == 1 and len(tx.scan("outbox")) == 1


def test_one_open_turn_per_session_freezes_conversation_order():
    svc, desk, session_id = opened()
    submit(desk, session_id)
    with pytest.raises(DeskRefused) as refused:
        submit(desk, session_id, text="두번째 질문")
    assert refused.value.reason_code == "session_busy"
    with svc.store.transaction() as tx:
        assert len(tx.scan(BUCKET_REQUESTS)) == 1


def test_session_request_bound_refuses_rather_than_discarding_history():
    svc, desk, session_id = opened()
    with svc.store.transaction() as tx:
        for index in range(desk_domain.MAX_REQUESTS_PER_SESSION):
            row = {"id": str(uuid4()), "session_id": session_id, "intent": "consult",
                   "text": "과거 질문", "originator": "local_user", "sequence": index + 1,
                   "status": "answered", "reason_code": None, "base_revision": REVISION,
                   "correlation_id": "c", "message_id": "m" + str(index), "task_id": None,
                   "owner_token": None, "answer": None, "execution_ref": None,
                   "created_at": "2026-09-19T00:00:00+00:00", "updated_at": "2026-09-19T00:00:00+00:00",
                   "dispatched_at": None, "finished_at": None}
            tx.put(BUCKET_REQUESTS, row["id"], row)
    with pytest.raises(DeskRefused) as refused:
        submit(desk, session_id, text="101번째")
    assert refused.value.reason_code == "session_full"
    with svc.store.transaction() as tx:
        assert len(tx.scan(BUCKET_REQUESTS)) == desk_domain.MAX_REQUESTS_PER_SESSION


def test_unknown_session_is_refused_and_listing_is_bounded_and_ordered():
    svc, desk, session_id = opened()
    with pytest.raises(DeskRefused) as refused:
        submit(desk, str(uuid4()))
    assert refused.value.reason_code == "session_unknown"
    for index in range(desk_domain.MAX_SESSIONS + 3):
        desk.create_session({"session_id": str(uuid4()), "title": "세션 " + str(index)})
    listing = desk.sessions()
    assert listing["schema"] == "urn:zeus:desk:1" and listing["truncated"] is True
    assert len(listing["sessions"]) == desk_domain.MAX_SESSIONS
    detail = desk.session(session_id)
    assert detail["session"]["session_id"] == session_id and detail["requests"] == []
    with pytest.raises(DeskRefused) as unknown:
        desk.session(str(uuid4()))
    assert unknown.value.reason_code == "session_unknown"


# ----- evidence and answer bounds ------------------------------------------------------------
def test_prior_conversation_is_bounded_and_reports_what_it_omitted():
    rows = [{"id": "r%02d" % index, "sequence": index, "intent": "consult", "status": "answered",
             "text": "질문 %02d" % index, "answer": {"answer": "응답 %02d" % index}}
            for index in range(1, 16)]
    history = prior_turns(rows)
    assert len(history["turns"]) == desk_domain.PRIOR_TURNS and history["omitted_turns"] == 5
    assert history["turns"][-1]["request_id"] == "r15"
    long_rows = [{"id": "l%d" % index, "sequence": index, "intent": "consult", "status": "answered",
                  "text": "x" * 4000, "answer": {"answer": "y" * 4000}} for index in range(1, 11)]
    bounded = prior_turns(long_rows)
    assert bounded["characters"] <= desk_domain.PRIOR_CHARS and bounded["omitted_turns"] >= 1
    assert prior_turns([{"id": "q", "sequence": 1, "intent": "consult", "status": "queued",
                         "text": "t", "answer": None}])["turns"] == []


def test_evidence_carries_only_conversation_and_owner_configured_base():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id, text="배포 상태 알려줘")
    evidence = desk.evidence(accepted["request"]["id"], snapshot={"sources": {"fleet": {"status": "observed"}}})
    assert evidence["frontdesk"]["base_revision"] == REVISION
    assert evidence["current_request"] == {"intent": "consult", "text": "배포 상태 알려줘"}
    assert evidence["prior_conversation"]["turns"] == []
    assert evidence["fleet_snapshot"] == {"sources": {"fleet": {"status": "observed"}}}
    flat = canonical(evidence)
    for forbidden in ("per_host", "total", "model", "provider", "HARNESS_DATABASE_URL"):
        assert forbidden not in flat


@pytest.mark.parametrize("document, code", [
    ({"answer": ""}, "invalid_answer"),
    ({"answer": 5}, "invalid_answer"),
    ({"answer": "ok", "objective": 3}, "invalid_answer"),
    ({"answer": "ok", "acceptance_criteria": "not-a-list"}, "invalid_answer"),
    ("plain string", "invalid_answer"),
])
def test_malformed_answers_are_refused(document, code):
    with pytest.raises(DeskRefused) as refused:
        validate_answer(document)
    assert refused.value.reason_code == code


def test_answer_fields_are_bounded_in_the_consumer():
    bounded = validate_answer({"answer": "긴 " * 20000, "objective": "o" * 5000,
                               "acceptance_criteria": ["c" * 900] * 40, "questions": ["q"] * 40})
    assert len(bounded["answer"]) <= desk_domain.ANSWER_MAX
    assert len(bounded["objective"]) <= desk_domain.OBJECTIVE_MAX
    assert len(bounded["acceptance_criteria"]) == desk_domain.LIST_ITEMS
    assert all(len(item) <= desk_domain.LIST_ITEM_MAX for item in bounded["acceptance_criteria"])
    assert "unverified" in bounded["authority"]


# ----- claim, turn and terminal states --------------------------------------------------------
def test_claim_is_one_turn_at_a_time_and_is_never_taken_over():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    claimed = desk.claim_next()
    assert claimed["status"] == "dispatching" and claimed["owner_token"]
    assert desk.claim_next() is None  # a live claim is never re-issued, in this or another process
    with pytest.raises(DeskRefused) as refused:
        desk.finalize(accepted["request"]["id"], "someone-else", status="answered")
    assert refused.value.reason_code == "owner_mismatch"
    desk.finalize(accepted["request"]["id"], claimed["owner_token"], status="answered", answer=validate_answer(ANSWER))
    with pytest.raises(DeskRefused) as terminal:
        desk.finalize(accepted["request"]["id"], claimed["owner_token"], status="answered")
    assert terminal.value.reason_code == "not_dispatching"


@pytest.mark.parametrize("intent, expected", [("consult", "answered"), ("request", "needs_spec")])
def test_turn_reaches_the_executor_and_binds_the_answer_to_its_request(intent, expected):
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id, intent=intent)
    request_id = accepted["request"]["id"]
    executor = FakeExecutor(svc)
    desk_runner, bus = runner(svc, desk, executor)
    step = desk_runner.step()
    assert step["status"] == expected and step["request_id"] == request_id
    assert executor.calls[0]["agent"] == LEAD
    assert executor.calls[0]["expected"]["id"] == message_id_of(request_id)
    row = desk.request(request_id)
    assert row["answer"]["answer"] == ANSWER["answer"] and row["task_id"] == message_id_of(request_id)
    assert row["execution_ref"] == ANSWER["execution_ref"] and row["finished_at"]
    # The assignment was published and acknowledged, and the result went to the conductor.
    recipients = [message["who"]["recipient"] for message in bus.published]
    assert recipients == [LEAD, "conductor"] and bus.acked
    # No follow-up assignment, candidate or approval comes out of a conversation.
    assert [m for m in bus.published if m["type"] == "task.assign" and m["who"]["recipient"] != LEAD] == []
    view = desk.session(session_id)["requests"][0]
    assert view["status"] == expected and view["answer"]["authority"].startswith("model_answer")
    assert "owner_token" not in view and "message_sha256" not in view


def test_desk_turn_writes_no_knowledge_and_queues_no_command():
    svc, desk, session_id = opened()
    submit(desk, session_id, intent="request", text="관측소에 새 화면을 만들어줘")
    desk_runner, bus = runner(svc, desk, FakeExecutor(svc))
    assert desk_runner.step()["status"] == "needs_spec"
    with svc.store.transaction() as tx:
        assert tx.scan("knowledge_nodes") == [] and tx.scan("operations") == []
        assert tx.scan("decisions_pending") == []


@pytest.mark.parametrize("status, code", [("failed", "execution_failed"), ("retry", "execution_retry")])
def test_injected_execution_failure_is_never_reported_as_sent_or_answered(status, code):
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    executor = FakeExecutor(svc, status=status)  # injected failure; no provider is involved
    desk_runner, _ = runner(svc, desk, executor)
    step = desk_runner.step()
    assert step["status"] == "failed" and step["reason_code"] == code
    row = desk.request(accepted["request"]["id"])
    assert row["answer"] is None and row["status"] == "failed"


def test_injected_timeout_fails_the_turn_without_a_second_provider_entry():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    executor = FakeExecutor(svc, error=TimeoutError("injected provider timeout"))
    desk_runner, _ = runner(svc, desk, executor)
    step = desk_runner.step()
    assert step["status"] == "failed" and step["reason_code"] == "exception:TimeoutError"
    # The identity is stable: the same request id replays its terminal row and claims nothing new.
    replay = submit(desk, session_id, request_id=accepted["request"]["id"])
    assert replay["cached"] is True and replay["request"]["status"] == "failed"
    assert desk.claim_next() is None and len(executor.calls) == 1


def test_settlement_failure_is_reconciliation_not_an_answer():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    # An injected counted-but-unsettled machine slot, the BudgetedExecutor's own record shape.
    executor = FakeExecutor(svc, slots=[{"id": "slot-1", "settled": False}])
    desk_runner, _ = runner(svc, desk, executor)
    step = desk_runner.step()
    assert step["status"] == "needs_reconciliation" and step["reason_code"] == "settlement_failed"
    assert desk.request(accepted["request"]["id"])["answer"] is None


def test_a_foreign_stream_entry_fails_this_turn_and_is_left_pending():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    bus = FakeBus()
    other_desk = FrontDesk(Harness(MemoryStore(), organization()), REVISION)
    other_session = str(uuid4())
    other_desk.create_session({"session_id": other_session, "title": "다른 데스크"})
    foreign = other_desk.submit({"session_id": other_session, "request_id": str(uuid4()),
                                 "intent": "consult", "text": "남의 메시지"})
    with other_desk.store.transaction() as tx:
        bus.publish(tx.get("outbox", message_id_of(foreign["request"]["id"]))["message"])
    executor = FakeExecutor(svc)
    desk_runner, _ = runner(svc, desk, executor, bus)
    step = desk_runner.step()
    assert step["status"] == "failed" and step["reason_code"] == "message_foreign"
    assert executor.calls == [] and bus.acked == []  # another actor's entry is never consumed
    assert desk.request(accepted["request"]["id"])["answer"] is None


def test_a_missing_stream_entry_fails_the_turn_without_execution():
    svc, desk, session_id = opened()
    submit(desk, session_id)

    class EmptyBus(FakeBus):
        def receive(self, agent, consumer, idle_ms=60000):
            return None

    executor = FakeExecutor(svc)
    desk_runner, _ = runner(svc, desk, executor, EmptyBus())
    step = desk_runner.step()
    assert step["status"] == "failed" and step["reason_code"] == "message_missing"
    assert executor.calls == []


def test_execution_guard_refuses_a_foreign_queued_task_before_any_entry():
    svc, desk, session_id = opened()
    submit(desk, session_id)
    desk_runner, bus = runner(svc, desk, FakeExecutor(svc))
    row = desk.claim_next()
    desk_runner._flush(row["correlation_id"])
    desk_runner._deliver(row)
    workflow = Workflow(svc.store, svc.org)
    with pytest.raises(ClaimGuardRefused):
        workflow.claim(LEAD, "other-owner", expected={"id": "desk-" + str(uuid4()),
                                                      "correlation_id": row["correlation_id"],
                                                      "statuses": {"queued"}})


# ----- restart and recovery -------------------------------------------------------------------
def test_restart_finalizes_a_succeeded_turn_without_another_provider_call():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    executor = FakeExecutor(svc)
    desk_runner, bus = runner(svc, desk, executor)
    row = desk.claim_next()
    desk_runner._flush(row["correlation_id"])
    desk_runner._deliver(row)
    executor.execute_one(LEAD, expected={"id": row["message_id"],
                                         "correlation_id": row["correlation_id"], "statuses": {"queued"}})
    # The process is interrupted here: the turn is still dispatching, its task already succeeded.
    restarted_executor = FakeExecutor(svc)
    restarted, _ = runner(svc, FrontDesk(svc, REVISION), restarted_executor, bus)
    recovered = restarted.recover()
    assert recovered["finalized"] == [accepted["request"]["id"]] and recovered["needs_reconciliation"] == []
    assert restarted_executor.calls == []
    assert desk.request(accepted["request"]["id"])["status"] == "answered"


def test_restart_without_a_matching_result_keeps_the_uncertainty():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    desk.claim_next()
    executor = FakeExecutor(svc)
    restarted, _ = runner(svc, FrontDesk(svc, REVISION), executor)
    recovered = restarted.recover()
    assert recovered["needs_reconciliation"] == [accepted["request"]["id"]] and executor.calls == []
    row = desk.request(accepted["request"]["id"])
    assert row["status"] == "needs_reconciliation" and row["reason_code"] == "interrupted_owner"
    assert row["text"] == "지금 상태가 어때?"  # history is retained, never discarded
    assert desk.claim_next() is None  # a queued turn is not re-created by recovery


def test_queued_work_survives_a_restart_and_runs_afterwards():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    executor = FakeExecutor(svc)
    desk_runner, _ = runner(svc, FrontDesk(svc, REVISION), executor)
    summary = desk_runner.run(once=True)
    assert summary["recovered"] == {"finalized": [], "needs_reconciliation": []}
    assert [turn["status"] for turn in summary["turns"]] == ["answered"]
    assert desk.request(accepted["request"]["id"])["status"] == "answered"
    assert desk_runner.run(once=True)["turns"] == []


def test_stop_prevents_a_new_claim():
    svc, desk, session_id = opened()
    submit(desk, session_id)
    executor = FakeExecutor(svc)
    desk_runner, _ = runner(svc, desk, executor)
    desk_runner.stop()
    assert desk_runner.step() == {"action": "idle"} and executor.calls == []
    assert desk.request(desk.session(session_id)["requests"][0]["request_id"])["status"] == "queued"


# ----- the executor's conversational branch ----------------------------------------------------
class FakeGit:
    def __init__(self, revision=REVISION, dirty=False):
        self.revision, self.dirty, self.workspaces = revision, dirty, []

    def review_workspace(self, revision, review_id):
        self.workspaces.append((revision, review_id))
        return "/tmp/review-" + review_id

    def _git(self, *args, cwd=None, strip=True):
        if args[:2] == ("rev-parse", "HEAD"):
            return self.revision
        if args[0] == "status":
            return "M file.py" if self.dirty else ""
        raise AssertionError("unexpected git call: " + str(args))


def desk_task(svc, desk, session_id, intent="consult"):
    accepted = submit(desk, session_id, intent=intent)
    with svc.store.transaction() as tx:
        message = tx.get("outbox", message_id_of(accepted["request"]["id"]))["message"]
    return accepted["request"], {"id": message["message_id"], "message": message}


def fake_executor_object(svc, answer, git=None, recorder=None):
    def _run(agent, key, objective, evidence, cwd, schema, read_only=False, heartbeat=None, lease=None,
             stage=None, workload="final_validation", importance=None, action=None, max_handoffs=4,
             delivery=None):
        (recorder if recorder is not None else []).append(
            {"agent": agent, "objective": objective, "evidence": evidence, "cwd": cwd, "schema": schema,
             "read_only": read_only, "workload": workload, "action": action, "max_handoffs": max_handoffs})
        return dict(answer)

    return SimpleNamespace(service=svc, git=git or FakeGit(), _run=_run)


def test_conversational_branch_runs_read_only_in_a_clean_checkout_at_the_request_base():
    from codex_harness.adapters.frontdesk import execute_frontdesk

    svc, desk, session_id = opened()
    row, task = desk_task(svc, desk, session_id, intent="request")
    calls, git = [], FakeGit()
    result = execute_frontdesk(fake_executor_object(svc, {**ANSWER, "objective": "관측소 개선"}, git, calls), task)
    assert git.workspaces == [(REVISION, "desk-" + row["id"])]
    call = calls[0]
    assert call["read_only"] is True and call["max_handoffs"] == 1 and call["action"] == "frontdesk"
    assert call["cwd"] == "/tmp/review-desk-" + row["id"]
    assert call["evidence"]["current_request"]["text"] == row["text"]
    assert set(call["schema"]["properties"]) == {"answer", "objective", "acceptance_criteria", "questions"}
    assert result["objective"] == "관측소 개선" and result["frontdesk"]["request_id"] == row["id"]
    assert "candidate" not in result  # a conversation produces no candidate and no approval


def test_conversational_branch_refuses_a_dirty_or_moved_checkout():
    from codex_harness.adapters.frontdesk import execute_frontdesk

    svc, desk, session_id = opened()
    _, task = desk_task(svc, desk, session_id)
    with pytest.raises(Exception, match="dirty"):
        execute_frontdesk(fake_executor_object(svc, ANSWER, FakeGit(dirty=True)), task)
    with pytest.raises(Exception, match="revision changed"):
        execute_frontdesk(fake_executor_object(svc, ANSWER, FakeGit(revision="b" * 40)), task)


def test_conversational_branch_refuses_a_malformed_answer():
    from codex_harness.adapters.frontdesk import execute_frontdesk

    svc, desk, session_id = opened()
    _, task = desk_task(svc, desk, session_id)
    with pytest.raises(ValueError, match="invalid_answer"):
        execute_frontdesk(fake_executor_object(svc, {"answer": "   "}), task)
