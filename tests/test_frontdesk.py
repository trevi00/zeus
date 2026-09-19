"""Local front door (local-operations-desk-001, part B): durable turns and the conductor handoff.

Every executor and bus here is an injected stand-in. No test in this file calls Codex, Claude or
any other provider, and an injected failure is labelled as injected: these are contract tests over
the real store, Workflow, outbox and organization, not evidence that a model ran.
"""
import json
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.frontdesk import (
    BUCKET_REQUESTS,
    LEAD,
    SUMMARY_TURNS,
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
    enters a provider. `answer` is injected, and `error`/`status` are injected failures.

    `slots` are machine call slots that already existed (earlier turns); `slot` is the record this
    call appends, exactly as `BudgetedExecutor` appends one per provider entry.
    """

    def __init__(self, svc, answer=None, status="succeeded", error=None, slots=None, slot=None):
        self.svc, self.answer, self.status, self.error = svc, answer or dict(ANSWER), status, error
        self.slots = list(slots) if slots is not None else []
        self.slot = slot if slot is not None else {"id": "slot-ok", "kind": "task", "settled": True}
        self.calls = []

    def execute_one(self, agent, expected=None):
        self.calls.append({"agent": agent, "expected": expected})
        self.slots.append(dict(self.slot, id=self.slot["id"] + "-" + str(len(self.calls))))
        workflow = Workflow(self.svc.store, self.svc.org)
        task = workflow.claim(agent, "desk-owner-" + uuid4().hex, expected=expected)
        if task is None:
            return None
        if self.error is not None:
            raise self.error
        if self.status != "succeeded":
            return workflow.fail(task, "injected failure", retryable=self.status == "retry")
        return workflow.complete(task, dict(self.answer), [])


class FakeCollector:
    """Stand-in for the observation collector: it records that a drain was asked for."""

    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def collect(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {"files": 1, "records": 2, "inserted": 2, "sink_failures": 0, "corrupt": 0,
                "refused": 0, "extra": "dropped"}


def runner(svc, desk, executor, bus=None, collector=None):
    bus = bus if bus is not None else FakeBus()
    return DeskRunner(svc, desk, executor, bus, Workflow(svc.store, svc.org),
                      collector=collector), bus


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
    executor = FakeExecutor(svc, slot={"id": "slot-1", "kind": "task", "settled": False})
    desk_runner, _ = runner(svc, desk, executor)
    step = desk_runner.step()
    assert step["status"] == "needs_reconciliation" and step["reason_code"] == "settlement_failed"
    assert desk.request(accepted["request"]["id"])["answer"] is None
    receipt = desk.receipt(accepted["request"]["id"])
    assert receipt["settled"] is False and receipt["calls"]["reserved"] == 1


def test_an_earlier_turns_unsettled_slot_does_not_contaminate_a_later_turn():
    svc, desk, session_id = opened()
    # A previous turn of this process left a counted-but-unsettled slot on the wrapper.
    executor = FakeExecutor(svc, slots=[{"id": "slot-old", "kind": "task", "settled": False}])
    accepted = submit(desk, session_id)
    desk_runner, _ = runner(svc, desk, executor)
    step = desk_runner.step()
    assert step["status"] == "answered" and step["reason_code"] is None
    receipt = desk.receipt(accepted["request"]["id"])
    # The receipt counts ONLY this turn's own call.
    assert receipt["calls"]["reserved"] == 1 and receipt["settled"] is True
    assert [slot["id"] for slot in receipt["calls"]["slots"]] == ["slot-ok-1"]
    assert receipt["task_id"] == message_id_of(accepted["request"]["id"])
    assert receipt["published"] is True


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
class UnavailableFinalize(FrontDesk):
    """An injected storage failure at exactly the terminal write; everything before it is durable."""

    def finalize(self, *args, **kwargs):
        raise RuntimeError("injected store failure at the terminal write")


def test_a_terminal_write_failure_leaves_the_turn_dispatching_and_stops_the_process():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    request_id = accepted["request"]["id"]
    executor = FakeExecutor(svc)
    desk_runner, _ = runner(svc, UnavailableFinalize(svc, REVISION), executor)
    step = desk_runner.step()
    assert step == {"action": "unavailable", "request_id": request_id,
                    "reason_code": "storage_unavailable", "error_type": "RuntimeError"}
    # No retry of this turn: it stays dispatching for the next startup, with its receipt durable.
    assert desk_runner.stopping is True and len(executor.calls) == 1
    assert desk.request(request_id)["status"] == "dispatching"
    assert desk.receipt(request_id)["settled"] is True


def test_restart_finalizes_a_receipted_turn_without_another_provider_call():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    request_id = accepted["request"]["id"]
    executor = FakeExecutor(svc)
    interrupted, bus = runner(svc, UnavailableFinalize(svc, REVISION), executor)
    interrupted.step()  # the turn ran and was receipted; the process died before its final status
    restarted_executor = FakeExecutor(svc)
    restarted, _ = runner(svc, FrontDesk(svc, REVISION), restarted_executor, bus)
    recovered = restarted.recover()
    assert recovered == {"finalized": [request_id], "needs_reconciliation": []}
    assert restarted_executor.calls == []
    row = desk.request(request_id)
    assert row["status"] == "answered" and row["answer"]["answer"] == ANSWER["answer"]


def test_a_succeeded_task_without_a_receipt_stays_unknown_instead_of_answered():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    request_id = accepted["request"]["id"]
    executor = FakeExecutor(svc)
    desk_runner, bus = runner(svc, desk, executor)
    row = desk.claim_next()
    desk_runner._flush(row["correlation_id"])
    desk_runner._deliver(row)
    executor.execute_one(LEAD, expected={"id": row["message_id"],
                                         "correlation_id": row["correlation_id"], "statuses": {"queued"}})
    # Interrupted between the machine settlement and the durable receipt: the accounting of this
    # turn is unknown, so the stored result is NOT promoted to an answer.
    assert desk.receipt(request_id) is None
    restarted_executor = FakeExecutor(svc)
    restarted, _ = runner(svc, FrontDesk(svc, REVISION), restarted_executor, bus)
    recovered = restarted.recover()
    assert recovered == {"finalized": [], "needs_reconciliation": [request_id]}
    assert restarted_executor.calls == []
    stored = desk.request(request_id)
    assert stored["status"] == "needs_reconciliation" and stored["reason_code"] == "accounting_unknown"
    assert stored["answer"] is None and stored["text"] == "지금 상태가 어때?"


def test_recovery_refuses_a_receipt_that_binds_another_turn():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    request_id = accepted["request"]["id"]
    executor = FakeExecutor(svc)
    interrupted, bus = runner(svc, UnavailableFinalize(svc, REVISION), executor)
    interrupted.step()
    with svc.store.transaction() as tx:
        receipt = tx.get("desk_receipts", request_id)
        tx.put("desk_receipts", request_id, {**receipt, "task_id": "desk-" + str(uuid4())})
    restarted, _ = runner(svc, FrontDesk(svc, REVISION), FakeExecutor(svc), bus)
    assert restarted.recover() == {"finalized": [], "needs_reconciliation": [request_id]}
    assert desk.request(request_id)["reason_code"] == "accounting_unknown"


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


def test_a_dispatch_exception_ends_the_turn_in_explicit_uncertainty():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)

    class BrokenBus(FakeBus):
        def receive(self, agent, consumer, idle_ms=60000):
            raise RuntimeError("injected transport failure")

    executor = FakeExecutor(svc)
    desk_runner, _ = runner(svc, desk, executor, BrokenBus())
    step = desk_runner.step()
    assert step["status"] == "needs_reconciliation"
    assert step["reason_code"] == "dispatch_exception:RuntimeError"
    # Storage worked, so the turn has a durable terminal record; nothing was executed or retried.
    assert executor.calls == [] and desk.claim_next() is None
    assert desk.request(accepted["request"]["id"])["answer"] is None


def test_observations_are_collected_after_recovery_and_after_each_turn():
    svc, desk, session_id = opened()
    submit(desk, session_id)
    collector = FakeCollector()
    desk_runner, _ = runner(svc, desk, FakeExecutor(svc), collector=collector)
    summary = desk_runner.run(once=True)
    assert collector.calls == 2  # once after recovery, once after the turn
    assert summary["collection"] == {"files": 1, "records": 2, "inserted": 2, "sink_failures": 0,
                                     "corrupt": 0, "refused": 0}
    assert summary["turns"][0]["collection"]["records"] == 2


def test_a_collection_failure_is_reported_and_never_hides_the_turn():
    svc, desk, session_id = opened()
    accepted = submit(desk, session_id)
    collector = FakeCollector(error=OSError("injected spool failure"))
    desk_runner, _ = runner(svc, desk, FakeExecutor(svc), collector=collector)
    summary = desk_runner.run(once=True)
    assert summary["collection"] == {"error_type": "OSError"}
    assert summary["turns"][0]["status"] == "answered"
    assert summary["turns"][0]["collection"] == {"error_type": "OSError"}
    assert desk.request(accepted["request"]["id"])["status"] == "answered"


def test_the_loop_summary_stays_bounded_and_reports_what_it_omitted():
    svc, desk, session_id = opened()
    desk_runner, _ = runner(svc, desk, FakeExecutor(svc))
    summary = {"turns": [], "turn_count": 0, "omitted_turns": 0, "statuses": {}}
    total = SUMMARY_TURNS + 10
    for index in range(total):
        desk_runner._record(summary, {"action": "turn", "request_id": "r%d" % index,
                                      "status": "answered" if index % 2 else "failed"})
    assert summary["turn_count"] == total and len(summary["turns"]) == SUMMARY_TURNS
    assert summary["omitted_turns"] == 10 and summary["turns"][0]["request_id"] == "r10"
    assert summary["statuses"] == {"answered": total // 2, "failed": total // 2}


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


def test_the_host_lock_and_observer_are_released_when_the_wiring_fails(tmp_path, monkeypatch):
    from filelock import FileLock

    import codex_harness.bootstrap as bootstrap
    from codex_harness.adapters import configuration, frontdesk_cli

    closed = []
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(bootstrap, "build_observer",
                        lambda *args, **kwargs: SimpleNamespace(close=lambda: closed.append(True)))

    def broken(service, args, observer):
        raise RuntimeError("injected wiring failure")  # e.g. an unreachable Redis or budget

    monkeypatch.setattr(frontdesk_cli, "build_runner", broken)
    with pytest.raises(RuntimeError):
        frontdesk_cli.run(service(), SimpleNamespace(revision=REVISION, once=True, desk_command="run"))
    assert closed == [True]
    lock = FileLock(str(tmp_path / "frontdesk.lock"), timeout=0)
    lock.acquire()  # the desk lock is free for the next start; it was not leaked
    lock.release()


# ----- the sanitized owner-runtime monitoring evidence -----------------------------------------
FLEET_DATA = {"schema": "urn:zeus:fleet-status:1", "registered": True, "id": "fleet-local",
              "paused": False, "max_parallel": 2,
              "budget": {"per_host": 192, "total": 192, "mode": "subscription"},
              "accounting_mode": "subscription",
              "lanes": [{"id": "lane-a", "team": "team-a", "active_job": "job-1"},
                        {"id": "lane-b", "team": "team-b", "active_job": None}],
              "jobs": [{"id": "job-1", "lane": "lane-a", "team": "team-a", "status": "running",
                        "reason_code": None, "operation_id": "op-1",
                        "goal": {"path": "docs/zeus/operations/secret-plan/SPEC.md",
                                 "criterion": "숨겨진 목표 문장"},
                        "dependencies": [], "calls": {"reserved": 1, "settled": 1},
                        "created_at": "2026-09-19T00:00:00+00:00",
                        "updated_at": "2026-09-19T00:00:00+00:00"}],
              "truncated": False}
OBSERVATION_DATA = {"events": {"total": 120, "high_severity_total": 7},
                    "sample": {"truncated": True},
                    "terminations": {"by_status": {"pending": 1}, "pending": 1},
                    "local": {"status": "ok", "pending_terminations": 1, "unreadable_terminations": 0,
                              "pending_alerts": 2}}


def monitoring_document(collected_at="2026-09-19T12:00:00+00:00", **sources):
    return {"schema": "harness-monitor.v1", "collected_at": collected_at,
            "scope": {"label": "repository zeus", "docker": "compose", "containers": None},
            "sources": {"database": {"status": "ok", "observed_at": collected_at, "data": {}},
                        "docker": {"status": "unavailable", "observed_at": collected_at,
                                   "error": "DockerUnavailable", "data": None},
                        "fleet": {"status": "ok", "observed_at": collected_at, "data": FLEET_DATA},
                        "observations": {"status": "ok", "observed_at": collected_at,
                                         "data": OBSERVATION_DATA},
                        **sources}}


def written(tmp_path, document):
    path = tmp_path / "monitoring.json"
    path.write_text(json.dumps(document, ensure_ascii=False), "utf-8")
    return path


def test_monitoring_facts_are_bounded_sanitized_and_dated():
    from codex_harness.adapters.frontdesk import monitoring_facts

    now = datetime.fromisoformat("2026-09-19T12:00:30+00:00")
    facts = monitoring_facts(monitoring_document(), now=now)
    assert facts["availability"] == "observed" and facts["freshness"] == "current"
    assert facts["age_seconds"] == 30 and facts["schema"] == "urn:zeus:desk-monitoring:1"
    assert facts["sources"]["docker"] == {"status": "unavailable", "error_type": "DockerUnavailable"}
    assert facts["fleet"]["accounting_mode"] == "subscription" and facts["fleet"]["registered"] is True
    assert facts["fleet"]["active_lanes"] == 1 and facts["fleet"]["sampled_jobs_by_status"] == {"running": 1}
    assert facts["observations"]["pending"] == {"terminations_recorded": 1, "terminations_local": 1,
                                                "unreadable_terminations": 0, "alerts": 2}
    assert facts["observations"]["history"]["sampled_high_severity"] == 7
    flat = canonical(facts)
    # No goal text, path, ceiling number or raw log line reaches the conversation evidence.
    for forbidden in ("docs/zeus", "숨겨진 목표 문장", "op-1", "per_host", "192"):
        assert forbidden not in flat


@pytest.mark.parametrize("age, freshness", [(30, "current"), (600, "stale")])
def test_an_old_capture_is_stale_not_current(age, freshness):
    from codex_harness.adapters.frontdesk import monitoring_facts

    now = datetime.fromisoformat("2026-09-19T12:00:00+00:00")
    collected = (now - timedelta(seconds=age)).isoformat()
    assert monitoring_facts(monitoring_document(collected), now=now)["freshness"] == freshness


@pytest.mark.parametrize("document, code", [
    ("not a snapshot", "snapshot_invalid"),
    ({"schema": "harness-monitor.v1"}, "snapshot_invalid"),
    (None, "snapshot_invalid"),
])
def test_a_malformed_capture_is_explicitly_unknown(document, code):
    from codex_harness.adapters.frontdesk import monitoring_facts

    facts = monitoring_facts(document)
    assert facts["availability"] == "unknown" and facts["reason_code"] == code
    assert facts["fleet"] is None and facts["observations"] is None and facts["freshness"] == "unknown"


def test_an_unparsable_capture_time_is_unknown_freshness():
    from codex_harness.adapters.frontdesk import monitoring_facts

    facts = monitoring_facts(monitoring_document("어제"))
    assert facts["availability"] == "observed" and facts["freshness"] == "unknown"
    assert facts["collected_at"] is None and facts["age_seconds"] is None


@pytest.mark.parametrize("mode, expected", [
    ({"accounting_mode": "subscription", "budget_mode": "finite"}, "unknown"),
    ({"accounting_mode": "finite", "budget_mode": "finite"}, "finite"),
    ({"accounting_mode": None, "budget_mode": None}, "finite"),
    ({"accounting_mode": "made-up", "budget_mode": "made-up"}, "unknown"),
])
def test_contradictory_or_invalid_accounting_modes_are_unknown_never_silently_finite(mode, expected):
    from codex_harness.adapters.frontdesk import monitoring_facts

    data = {**FLEET_DATA, "budget": {"per_host": 1, "total": 1}}
    if mode["accounting_mode"] is None:
        data.pop("accounting_mode")
    else:
        data["accounting_mode"] = mode["accounting_mode"]
    if mode["budget_mode"] is not None:
        data["budget"] = {**data["budget"], "mode": mode["budget_mode"]}
    document = monitoring_document()
    document["sources"]["fleet"] = {"status": "ok", "data": data}
    assert monitoring_facts(document)["fleet"]["accounting_mode"] == expected


def test_an_unavailable_fleet_or_observation_source_is_unknown_not_healthy():
    from codex_harness.adapters.frontdesk import monitoring_facts

    document = monitoring_document()
    document["sources"]["fleet"] = {"status": "unavailable", "error": "OperationalError", "data": None}
    document["sources"]["observations"] = {"status": "ok", "data": None}
    facts = monitoring_facts(document)
    assert facts["fleet"] == {"availability": "unknown", "reason_code": "source_unavailable",
                              "error_type": "OperationalError"}
    assert facts["observations"]["availability"] == "unknown"


@pytest.mark.parametrize("write, code", [
    (None, "snapshot_missing"),
    ("{not json", "snapshot_unreadable"),
])
def test_a_missing_or_unreadable_capture_never_fails_the_turn(tmp_path, write, code):
    from codex_harness.adapters.frontdesk import monitoring_evidence

    path = tmp_path / "monitoring.json"
    if write is not None:
        path.write_text(write, "utf-8")
    facts = monitoring_evidence(path)
    assert facts["availability"] == "unknown" and facts["reason_code"] == code


def test_the_execution_helper_carries_the_owner_runtime_capture_as_evidence(tmp_path, monkeypatch):
    from codex_harness.adapters import frontdesk as frontdesk_adapter

    svc, desk, session_id = opened()
    row, task = desk_task(svc, desk, session_id)
    path = written(tmp_path, monitoring_document())
    monkeypatch.setattr(frontdesk_adapter, "snapshot_path", lambda: path)
    calls = []
    frontdesk_adapter.execute_frontdesk(fake_executor_object(svc, ANSWER, FakeGit(), calls), task)
    snapshot = calls[0]["evidence"]["fleet_snapshot"]
    assert snapshot["schema"] == "urn:zeus:desk-monitoring:1" and snapshot["availability"] == "observed"
    assert snapshot["fleet"]["accounting_mode"] == "subscription"
    assert snapshot["observations"]["pending"]["terminations_local"] == 1
    assert snapshot["freshness"] in {"current", "stale"} and snapshot["age_seconds"] is not None


def test_the_execution_helper_reports_an_absent_capture_as_unknown(tmp_path, monkeypatch):
    from codex_harness.adapters import frontdesk as frontdesk_adapter

    svc, desk, session_id = opened()
    _, task = desk_task(svc, desk, session_id)
    monkeypatch.setattr(frontdesk_adapter, "snapshot_path", lambda: tmp_path / "monitoring.json")
    calls = []
    result = frontdesk_adapter.execute_frontdesk(fake_executor_object(svc, ANSWER, FakeGit(), calls), task)
    snapshot = calls[0]["evidence"]["fleet_snapshot"]
    # The turn still runs: a missing capture is unknown evidence, never a provider failure.
    assert snapshot == {"schema": "urn:zeus:desk-monitoring:1", "availability": "unknown",
                        "reason_code": "snapshot_missing",
                        "authority": frontdesk_adapter.MONITORING_AUTHORITY, "collected_at": None,
                        "age_seconds": None, "freshness": "unknown", "sources": None,
                        "fleet": None, "observations": None}
    assert result["answer"] == ANSWER["answer"]


def test_conversational_branch_refuses_a_malformed_answer():
    from codex_harness.adapters.frontdesk import execute_frontdesk

    svc, desk, session_id = opened()
    _, task = desk_task(svc, desk, session_id)
    with pytest.raises(ValueError, match="invalid_answer"):
        execute_frontdesk(fake_executor_object(svc, {"answer": "   "}), task)
