"""Shared S8 scenario steps (`intake.frontdesk`): M7 `application/frontdesk.py` (`FrontDesk`, `DeskRunner`, `correlation_of`,
`message_id_of`), characterized BEFORE pilot 84 split-moves it (DESIGN-s8 §11 V16: FrontDesk -> intake, DeskRunner -> coordination).

Every case mirrors a test of M7 `tests/test_frontdesk.py` (the test name is the case label; a parametrized test is one case with
one entry per parameter), plus LABELLED additions that reach the branches of `FrontDesk`/`DeskRunner` the tests do not
(`_classify_result`, `_bound_execution`, the storage-failure stops, the receipt that is never rewritten, a runner without a bus).

**Not mirrored** (recorded in the result as `unreachable`, never silently dropped): the 28 tests that need the frontdesk adapter or
the CLI (`adapters/frontdesk.py`: the desk output schema, `execute_frontdesk`, `monitoring_facts`/`monitoring_evidence`;
`adapters/frontdesk_cli.py`, the signal and lock tests; `cli.desk_command`): S10 / layer 1. `test_frontdesk_http.py` (the HTTP
handler over a `FrontDesk`) is S10 as well.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. `api.FrontDesk(service, revision, **kw)` and
`api.DeskRunner(service, desk, executor, bus, workflow, **kw)` are CLASSES (a case subclasses `FrontDesk` to inject a storage
fault, as M7's `UnavailableFinalize`); `api.Harness(store, org)` builds the service, `api.Workflow(store, org)` the workflow;
`api.domain` is the front-door domain module (constants, `prior_turns`, `validate_answer`, `DeskRefused`); `api.advance(seconds)` moves
the scripted clock and `api.reset()` resets clock and ids. The executor, the bus and the collector are LABELLED doubles (the M7
`FakeExecutor`, `FakeBus`, `FakeCollector`: no provider, no Redis); the store is `MemoryStore`, the workflow, the outbox flusher and the
organization are the real ones. Ids the scenario chooses come from a local counter (not the harness's id source); the harness's
scripted ids still feed the default owner token and the envelope. For every refusal the digest of the whole store before and after is
recorded."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from types import SimpleNamespace

REVISION = "0" * 39 + "a"
TITLE = "로컬 운영 데스크"
ANSWER = {"answer": "구독 사용량은 기록되고 호출 수 상한은 적용되지 않습니다.", "objective": None,
          "acceptance_criteria": [], "questions": [], "execution_ref": "sha256:" + "b" * 64}
UNREACHABLE = {
    "adapter": "unreachable: frontdesk adapter (layer 1 / S10)",
    "cli": "unreachable: frontdesk CLI and signals (S10)",
    "monitoring": "unreachable: frontdesk monitoring evidence adapter (layer 1 / S10)"}
UNREACHABLE_TESTS = (
    ("test_the_desk_output_schema_requires_every_property_and_keeps_null_and_empty_values", "adapter"),
    ("test_conversational_branch_runs_read_only_in_a_clean_checkout_at_the_request_base", "adapter"),
    ("test_conversational_branch_refuses_a_dirty_or_moved_checkout", "adapter"),
    ("test_the_host_lock_and_observer_are_released_when_the_wiring_fails", "cli"),
    ("test_an_injected_storage_loss_is_a_durable_failure_and_a_nonzero_desk_exit", "cli"),
    ("test_a_storage_stopped_desk_run_exits_the_process_nonzero", "cli"),
    ("test_a_normal_idle_or_interrupted_desk_run_stays_successful", "cli"),
    ("test_an_actual_signal_while_running_stops_the_desk_gracefully_and_the_handlers_are_restored", "cli"),
    ("test_a_desk_runner_exception_restores_the_handlers_and_keeps_the_original_error", "cli"),
    ("test_a_partial_desk_handler_installation_restores_only_what_it_installed", "cli"),
    ("test_monitoring_facts_are_bounded_sanitized_and_dated", "monitoring"),
    ("test_an_old_capture_is_historical_not_current", "monitoring"),
    ("test_the_desk_and_the_readiness_endpoint_agree_on_one_freshness_rule", "monitoring"),
    ("test_each_source_carries_its_own_observed_at_age", "monitoring"),
    ("test_a_malformed_capture_is_explicitly_unknown", "monitoring"),
    ("test_a_malformed_nested_capture_is_unknown_evidence_and_never_raises", "monitoring"),
    ("test_a_malformed_container_is_unknown_not_zero", "monitoring"),
    ("test_an_unusable_capture_time_is_unknown_freshness", "monitoring"),
    ("test_a_capture_from_the_future_is_not_reported_as_current", "monitoring"),
    ("test_accounting_modes_and_their_explanations_never_silently_claim_a_ceiling", "monitoring"),
    ("test_an_unavailable_fleet_or_observation_source_is_unknown_not_healthy", "monitoring"),
    ("test_an_unregistered_fleet_makes_no_ceiling_claim", "monitoring"),
    ("test_a_missing_or_unreadable_capture_never_fails_the_turn", "monitoring"),
    ("test_an_oversized_or_unopenable_capture_is_unknown", "monitoring"),
    ("test_the_execution_helper_carries_the_owner_runtime_capture_as_evidence", "monitoring"),
    ("test_the_execution_helper_reports_a_malformed_capture_as_unknown_without_failing", "monitoring"),
    ("test_the_execution_helper_reports_an_absent_capture_as_unknown", "monitoring"),
    ("test_conversational_branch_refuses_a_malformed_answer", "adapter"))


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plain(value):
    """JSON-safe copy: sets become sorted lists, tuples lists."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    return value


class Counter:
    """The scenario's own deterministic uuid source (the harness's id source is left to the product)."""

    def __init__(self):
        self.n = 0

    def uuid(self) -> str:
        self.n += 1
        return str(uuid.UUID(int=(0xDE5C << 112) | self.n, version=4))

    def token(self) -> str:
        self.n += 1
        return "desk-owner-%d" % self.n


IDS = Counter()


def store_digest(store) -> str:
    with store.transaction() as tx:
        rows = tx.records()
    return canonical_digest(sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows))


def rows(store, bucket) -> list:
    with store.transaction() as tx:
        return plain(tx.scan(bucket))


def refused(store, fn, *args, **kwargs) -> dict:
    """Run `fn`; a refusal records its type, fixed code, field and message, and the store digest before and after."""
    before = store_digest(store)
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None),
                "field": getattr(exc, "field", None), "message": str(exc)[:200], "store_before": before,
                "store_after": store_digest(store)}
    return {"returned": plain(value), "store_before": before, "store_after": store_digest(store)}


# ---- LABELLED doubles (M7 `tests/test_frontdesk.py`) ----------------------------------------------------------------
def doubles(api):
    class FakeBus:
        """LABELLED. A stand-in transport with the RedisBus surface the outbox and the runner use."""

        def __init__(self):
            self.streams, self.published, self.acked = {}, [], []

        @staticmethod
        def validate(message):
            return api.validate_message(message)

        def publish(self, message):
            self.validate(message)
            entry_id = str(len(self.published) + 1)
            self.published.append(message)
            self.streams.setdefault(message["who"]["recipient"], []).append(
                (entry_id, {"body": api.canonical(message)}))
            return entry_id

        def receive(self, agent, consumer, idle_ms=60000):
            found = self.streams.get(agent) or []
            return found[0] if found else None

        def ack(self, agent, entry_id):
            self.acked.append(entry_id)
            self.streams[agent] = [row for row in self.streams.get(agent, []) if row[0] != entry_id]

        @staticmethod
        def decode(fields):
            return api.validate_message(json.loads(fields["body"]))

    class FakeExecutor:
        """LABELLED. Stand-in for the budgeted Codex executor: it drives the REAL claim/complete path but never enters a
        provider. `answer` is injected, and `error`/`status` are injected failures. `slots` already existed (earlier turns);
        `slot` is the record this call appends, as `BudgetedExecutor` appends one per provider entry."""

        def __init__(self, svc, answer=None, status="succeeded", error=None, slots=None, slot=None):
            self.svc, self.answer, self.status, self.error = svc, answer or dict(ANSWER), status, error
            self.slots = list(slots) if slots is not None else []
            self.slot = slot if slot is not None else {"id": "slot-ok", "kind": "task", "settled": True}
            self.calls = []

        def execute_one(self, agent, expected=None):
            self.calls.append({"agent": agent, "expected": expected})
            self.slots.append(dict(self.slot, id=self.slot["id"] + "-" + str(len(self.calls))))
            workflow = api.Workflow(self.svc.store, self.svc.org)
            task = workflow.claim(agent, IDS.token(), expected=expected)
            if task is None:
                return None
            if self.error is not None:
                raise self.error
            if self.status != "succeeded":
                return workflow.fail(task, "injected failure", retryable=self.status == "retry")
            return workflow.complete(task, dict(self.answer), [])

    class FakeCollector:
        """LABELLED. Stand-in for the observation collector: it records that a drain was asked for."""

        def __init__(self, error=None):
            self.error, self.calls = error, 0

        def collect(self):
            self.calls += 1
            if self.error is not None:
                raise self.error
            return {"files": 1, "records": 2, "inserted": 2, "sink_failures": 0, "corrupt": 0,
                    "refused": 0, "extra": "dropped"}

    class UnavailableFinalize(api.FrontDesk):
        """LABELLED injected storage failure at exactly the terminal write; everything before it is durable."""

        def finalize(self, *args, **kwargs):
            raise RuntimeError("injected store failure at the terminal write")

    class UnavailableClaim(api.FrontDesk):
        """LABELLED injected storage failure at the claim."""

        def claim_next(self):
            raise OSError("injected store failure at the claim")

    return SimpleNamespace(FakeBus=FakeBus, FakeExecutor=FakeExecutor, FakeCollector=FakeCollector,
                           UnavailableFinalize=UnavailableFinalize, UnavailableClaim=UnavailableClaim)


class World:
    """The M7 test helpers over the side's `api` and the doubles."""

    def __init__(self, api):
        self.api, self.d = api, doubles(api)

    def service(self):
        return self.api.Harness(self.api.MemoryStore(), self.api.organization())

    def opened(self, svc=None, title=TITLE):
        svc = svc or self.service()
        desk = self.api.FrontDesk(svc, REVISION)
        session_id = IDS.uuid()
        desk.create_session({"session_id": session_id, "title": title})
        self.api.advance(1)
        return svc, desk, session_id

    def submit(self, desk, session_id, text="지금 상태가 어때?", intent="consult", request_id=None):
        result = desk.submit({"session_id": session_id, "request_id": request_id or IDS.uuid(), "intent": intent,
                              "text": text})
        self.api.advance(1)
        return result

    def runner(self, svc, desk, executor, bus=None, collector=None):
        bus = bus if bus is not None else self.d.FakeBus()
        return self.api.DeskRunner(svc, desk, executor, bus, self.api.Workflow(svc.store, svc.org),
                                   collector=collector), bus

    def step(self, runner):
        out = runner.step()
        self.api.advance(1)
        return out


# ---- identity, bounds and idempotent intake ------------------------------------------------------------------------------
def g1_intake(api, w) -> dict:
    out = {}
    domain = api.domain

    # ---- test_session_creation_is_idempotent_and_refuses_a_second_title
    svc, desk, session_id = w.opened()
    out["test_session_creation_is_idempotent_and_refuses_a_second_title"] = {
        "again": plain(desk.create_session({"session_id": session_id, "title": TITLE})),
        "second_title": refused(svc.store, desk.create_session, {"session_id": session_id, "title": "다른 제목"}),
        "sessions": rows(svc.store, "desk_sessions"), "events": rows(svc.store, "desk_events")}

    # ---- test_session_body_is_bounded
    case = {}
    documents = [({"session_id": "not-a-uuid", "title": "t"}, "invalid_id"),
                 ({"session_id": IDS.uuid()}, "invalid_body"),
                 ({"session_id": IDS.uuid(), "title": "t", "extra": 1}, "invalid_body"),
                 ({"session_id": IDS.uuid(), "title": ""}, "text_out_of_bounds"),
                 ({"session_id": IDS.uuid(), "title": "x" * 201}, "text_out_of_bounds")]
    for index, (document, code) in enumerate(documents):
        svc, desk, _ = w.opened()
        case["%d_%s" % (index, code)] = refused(svc.store, desk.create_session, document)
    out["test_session_body_is_bounded"] = case

    # ---- test_submission_bounds_refuse_before_any_row
    case = {}
    for field, value, code in [("intent", "implement", "invalid_intent"), ("text", "", "text_out_of_bounds"),
                               ("text", "x" * 6001, "text_out_of_bounds"), ("text", "hello\x00there", "invalid_text"),
                               ("request_id", "12345", "invalid_id")]:
        svc, desk, session_id = w.opened()
        body = {"session_id": session_id, "request_id": IDS.uuid(), "intent": "consult", "text": "ok"}
        body[field] = value
        result = refused(svc.store, desk.submit, body)
        result.update(requests=rows(svc.store, "desk_requests"), outbox=rows(svc.store, "outbox"))
        case["%s_%s" % (field, code)] = result
    out["test_submission_bounds_refuse_before_any_row"] = case

    # ---- test_submission_persists_the_turn_and_its_assignment_together
    svc, desk, session_id = w.opened()
    request_id = IDS.uuid()
    accepted = w.submit(desk, session_id, request_id=request_id)
    with svc.store.transaction() as tx:
        outbox = tx.get("outbox", api.message_id_of(request_id))
        message = outbox["message"]
    case = {"accepted": plain(accepted), "request": plain(desk.request(request_id)),
            "outbox": plain(outbox), "session": rows(svc.store, "desk_sessions"),
            "events": rows(svc.store, "desk_events")}
    case["contract_valid"] = refused(svc.store, api.validate_message, message)["returned"] is not None
    case["authorized"] = refused(svc.store, svc.org.authorize, message)
    out["test_submission_persists_the_turn_and_its_assignment_together"] = case

    # ---- test_same_request_replays_and_a_changed_body_conflicts
    svc, desk, session_id = w.opened()
    request_id = IDS.uuid()
    first = w.submit(desk, session_id, request_id=request_id)
    replay = w.submit(desk, session_id, request_id=request_id)
    conflict = refused(svc.store, desk.submit, {"session_id": session_id, "request_id": request_id, "intent": "consult",
                                                "text": "다른 내용"})
    other_session = IDS.uuid()
    desk.create_session({"session_id": other_session, "title": "두번째"})
    other = refused(svc.store, desk.submit, {"session_id": other_session, "request_id": request_id, "intent": "consult",
                                             "text": "지금 상태가 어때?"})
    out["test_same_request_replays_and_a_changed_body_conflicts"] = {
        "first": plain(first), "replay": plain(replay), "replay_equals_first": replay["request"] == first["request"],
        "text_conflict": conflict, "session_conflict": other, "requests": len(rows(svc.store, "desk_requests")),
        "intent_conflict": refused(svc.store, desk.submit, {"session_id": session_id, "request_id": request_id,
                                                            "intent": "request", "text": "지금 상태가 어때?"})}

    # ---- test_concurrent_identical_submissions_create_exactly_one_turn (threads: only counts are recorded)
    svc, desk, session_id = w.opened()
    request_id, results, errors = IDS.uuid(), [], []

    def call():
        try:
            results.append(desk.submit({"session_id": session_id, "request_id": request_id, "intent": "consult",
                                        "text": "동시 제출"}))
        except Exception as exc:  # recorded, never swallowed
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=call) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    sequential_svc, sequential, sequential_session = w.opened()
    sequential_id = IDS.uuid()
    flags = [sequential.submit({"session_id": sequential_session, "request_id": sequential_id, "intent": "consult",
                                "text": "순차 제출"})["cached"] for _ in range(6)]
    out["test_concurrent_identical_submissions_create_exactly_one_turn"] = {
        "threaded": {"errors": errors, "results": len(results), "uncached": sum(1 for r in results if r["cached"] is False),
                     "requests": len(rows(svc.store, "desk_requests")), "outbox": len(rows(svc.store, "outbox"))},
        "sequential": {"cached_flags": flags, "requests": len(rows(sequential_svc.store, "desk_requests")),
                       "outbox": len(rows(sequential_svc.store, "outbox"))}}

    # ---- test_one_open_turn_per_session_freezes_conversation_order
    svc, desk, session_id = w.opened()
    w.submit(desk, session_id)
    out["test_one_open_turn_per_session_freezes_conversation_order"] = {
        "second": refused(svc.store, desk.submit, {"session_id": session_id, "request_id": IDS.uuid(), "intent": "consult",
                                                   "text": "두번째 질문"}),
        "requests": len(rows(svc.store, "desk_requests"))}

    # ---- test_session_request_bound_refuses_rather_than_discarding_history
    svc, desk, session_id = w.opened()
    with svc.store.transaction() as tx:
        for index in range(domain.MAX_REQUESTS_PER_SESSION):
            row = {"id": IDS.uuid(), "session_id": session_id, "intent": "consult", "text": "과거 질문",
                   "originator": "local_user", "sequence": index + 1, "status": "answered", "reason_code": None,
                   "base_revision": REVISION, "correlation_id": "c", "message_id": "m" + str(index), "task_id": None,
                   "owner_token": None, "answer": None, "execution_ref": None,
                   "created_at": "2026-09-19T00:00:00+00:00", "updated_at": "2026-09-19T00:00:00+00:00",
                   "dispatched_at": None, "finished_at": None}
            tx.put("desk_requests", row["id"], row)
    out["test_session_request_bound_refuses_rather_than_discarding_history"] = {
        "refused": refused(svc.store, desk.submit, {"session_id": session_id, "request_id": IDS.uuid(),
                                                    "intent": "consult", "text": "101번째"}),
        "requests": len(rows(svc.store, "desk_requests")), "limit": domain.MAX_REQUESTS_PER_SESSION}

    # ---- test_unknown_session_is_refused_and_listing_is_bounded_and_ordered
    svc, desk, session_id = w.opened()
    unknown_submit = refused(svc.store, desk.submit, {"session_id": IDS.uuid(), "request_id": IDS.uuid(),
                                                      "intent": "consult", "text": "t"})
    for index in range(domain.MAX_SESSIONS + 3):
        desk.create_session({"session_id": IDS.uuid(), "title": "세션 " + str(index)})
    listing = desk.sessions()
    detail = desk.session(session_id)
    out["test_unknown_session_is_refused_and_listing_is_bounded_and_ordered"] = {
        "unknown_submit": unknown_submit, "schema": listing["schema"], "truncated": listing["truncated"],
        "listed": len(listing["sessions"]), "listing": plain(listing), "limit": domain.MAX_SESSIONS,
        "detail": plain(detail), "unknown_session": refused(svc.store, desk.session, IDS.uuid()),
        "bad_session_id": refused(svc.store, desk.session, "not-a-uuid")}
    return out


def g2_evidence(api, w) -> dict:
    out = {}
    domain = api.domain

    # ---- test_prior_conversation_is_bounded_and_reports_what_it_omitted (domain function)
    history_rows = [{"id": "r%02d" % index, "sequence": index, "intent": "consult", "status": "answered",
                     "text": "질문 %02d" % index, "answer": {"answer": "응답 %02d" % index}} for index in range(1, 16)]
    history = domain.prior_turns(history_rows)
    long_rows = [{"id": "l%d" % index, "sequence": index, "intent": "consult", "status": "answered", "text": "x" * 4000,
                  "answer": {"answer": "y" * 4000}} for index in range(1, 11)]
    bounded = domain.prior_turns(long_rows)
    out["test_prior_conversation_is_bounded_and_reports_what_it_omitted"] = {
        "history": plain(history), "turns_limit": domain.PRIOR_TURNS, "bounded_characters": bounded["characters"],
        "bounded_omitted": bounded["omitted_turns"], "chars_limit": domain.PRIOR_CHARS,
        "queued": plain(domain.prior_turns([{"id": "q", "sequence": 1, "intent": "consult", "status": "queued",
                                             "text": "t", "answer": None}]))}

    # ---- test_evidence_carries_only_conversation_and_owner_configured_base
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id, text="배포 상태 알려줘")
    snapshot = {"sources": {"fleet": {"status": "observed"}}}
    evidence = desk.evidence(accepted["request"]["id"], snapshot=snapshot)
    flat = api.canonical(evidence)
    out["test_evidence_carries_only_conversation_and_owner_configured_base"] = {
        "evidence": plain(evidence), "no_snapshot": plain(desk.evidence(accepted["request"]["id"])),
        "forbidden_present": [name for name in ("per_host", "total", "model", "provider", "HARNESS_DATABASE_URL")
                              if name in flat],
        "unknown_request": refused(svc.store, desk.evidence, IDS.uuid())}

    # ---- test_malformed_answers_are_refused
    case = {}
    for index, document in enumerate([{"answer": ""}, {"answer": 5}, {"answer": "ok", "objective": 3},
                                      {"answer": "ok", "acceptance_criteria": "not-a-list"}, "plain string"]):
        try:
            domain.validate_answer(document)
            case[str(index)] = {"returned": True}
        except domain.DeskRefused as exc:
            case[str(index)] = {"refused": type(exc).__name__, "reason_code": exc.reason_code, "field": exc.field}
    out["test_malformed_answers_are_refused"] = case

    # ---- test_answer_fields_are_bounded_in_the_consumer
    answer = domain.validate_answer({"answer": "긴 " * 20000, "objective": "o" * 5000,
                                     "acceptance_criteria": ["c" * 900] * 40, "questions": ["q"] * 40})
    out["test_answer_fields_are_bounded_in_the_consumer"] = {
        "answer_length": len(answer["answer"]), "answer_max": domain.ANSWER_MAX,
        "objective_length": len(answer["objective"]), "objective_max": domain.OBJECTIVE_MAX,
        "criteria": len(answer["acceptance_criteria"]), "list_items": domain.LIST_ITEMS,
        "criteria_lengths": sorted({len(item) for item in answer["acceptance_criteria"]}),
        "questions": len(answer["questions"]), "authority": answer["authority"]}
    return out


# ---- claim, turn and terminal states -----------------------------------------------------------------------------------
def g3_turns(api, w) -> dict:
    out = {}
    d = w.d

    # ---- test_claim_is_one_turn_at_a_time_and_is_never_taken_over
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    request_id = accepted["request"]["id"]
    claimed = desk.claim_next()
    second_claim = desk.claim_next()
    wrong = refused(svc.store, desk.finalize, request_id, "someone-else", status="answered")
    finalized = desk.finalize(request_id, claimed["owner_token"], status="answered",
                              answer=api.domain.validate_answer(ANSWER))
    out["test_claim_is_one_turn_at_a_time_and_is_never_taken_over"] = {
        "claimed": plain(claimed), "second_claim": second_claim, "owner_mismatch": wrong, "finalized": plain(finalized),
        "terminal": refused(svc.store, desk.finalize, request_id, claimed["owner_token"], status="answered"),
        "events": rows(svc.store, "desk_events"), "session": rows(svc.store, "desk_sessions")}

    # ---- test_turn_reaches_the_executor_and_binds_the_answer_to_its_request
    case = {}
    for intent, expected in [("consult", "answered"), ("request", "needs_spec")]:
        svc, desk, session_id = w.opened()
        accepted = w.submit(desk, session_id, intent=intent)
        request_id = accepted["request"]["id"]
        executor = d.FakeExecutor(svc)
        desk_runner, bus = w.runner(svc, desk, executor)
        step = w.step(desk_runner)
        view = desk.session(session_id)["requests"][0]
        case[intent] = {
            "expected": expected, "step": plain(step), "calls": plain(executor.calls), "row": plain(desk.request(request_id)),
            "recipients": [m["who"]["recipient"] for m in bus.published], "acked": bus.acked,
            "other_assignments": [m["message_id"] for m in bus.published
                                  if m["type"] == "task.assign" and m["who"]["recipient"] != api.LEAD],
            "view": plain(view), "slots": plain(executor.slots), "receipt": plain(desk.receipt(request_id)),
            "events": rows(svc.store, "desk_events"), "tasks": rows(svc.store, "tasks"),
            "outbox": rows(svc.store, "outbox"), "published": plain(bus.published)}
    out["test_turn_reaches_the_executor_and_binds_the_answer_to_its_request"] = case

    # ---- test_desk_turn_writes_no_knowledge_and_queues_no_command
    svc, desk, session_id = w.opened()
    w.submit(desk, session_id, intent="request", text="관측소에 새 화면을 만들어줘")
    desk_runner, bus = w.runner(svc, desk, d.FakeExecutor(svc))
    step = w.step(desk_runner)
    with svc.store.transaction() as tx:
        scans = {bucket: tx.scan(bucket) for bucket in ("knowledge_nodes", "operations", "decisions_pending")}
    out["test_desk_turn_writes_no_knowledge_and_queues_no_command"] = {"step": plain(step), "scans": plain(scans)}

    # ---- test_injected_execution_failure_is_never_reported_as_sent_or_answered
    case = {}
    for status, code in [("failed", "execution_failed"), ("retry", "execution_retry")]:
        svc, desk, session_id = w.opened()
        accepted = w.submit(desk, session_id)
        executor = d.FakeExecutor(svc, status=status)  # injected failure; no provider is involved
        desk_runner, _ = w.runner(svc, desk, executor)
        step = w.step(desk_runner)
        case[status] = {"expected_code": code, "step": plain(step), "row": plain(desk.request(accepted["request"]["id"])),
                        "receipt": plain(desk.receipt(accepted["request"]["id"])), "tasks": rows(svc.store, "tasks")}
    out["test_injected_execution_failure_is_never_reported_as_sent_or_answered"] = case

    # ---- test_injected_timeout_fails_the_turn_without_a_second_provider_entry
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    executor = d.FakeExecutor(svc, error=TimeoutError("injected provider timeout"))
    desk_runner, _ = w.runner(svc, desk, executor)
    step = w.step(desk_runner)
    replay = w.submit(desk, session_id, request_id=accepted["request"]["id"])
    out["test_injected_timeout_fails_the_turn_without_a_second_provider_entry"] = {
        "step": plain(step), "replay": plain(replay), "claim_after": desk.claim_next(), "calls": len(executor.calls),
        "receipt": plain(desk.receipt(accepted["request"]["id"])), "tasks": rows(svc.store, "tasks")}

    # ---- test_settlement_failure_is_reconciliation_not_an_answer
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    executor = d.FakeExecutor(svc, slot={"id": "slot-1", "kind": "task", "settled": False})
    desk_runner, _ = w.runner(svc, desk, executor)
    step = w.step(desk_runner)
    out["test_settlement_failure_is_reconciliation_not_an_answer"] = {
        "step": plain(step), "row": plain(desk.request(accepted["request"]["id"])),
        "receipt": plain(desk.receipt(accepted["request"]["id"]))}

    # ---- test_an_earlier_turns_unsettled_slot_does_not_contaminate_a_later_turn
    svc, desk, session_id = w.opened()
    executor = d.FakeExecutor(svc, slots=[{"id": "slot-old", "kind": "task", "settled": False}])
    accepted = w.submit(desk, session_id)
    desk_runner, _ = w.runner(svc, desk, executor)
    step = w.step(desk_runner)
    out["test_an_earlier_turns_unsettled_slot_does_not_contaminate_a_later_turn"] = {
        "step": plain(step), "receipt": plain(desk.receipt(accepted["request"]["id"])),
        "message_id": api.message_id_of(accepted["request"]["id"])}

    # ---- test_a_foreign_stream_entry_fails_this_turn_and_is_left_pending
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    bus = d.FakeBus()
    other_desk = api.FrontDesk(w.service(), REVISION)
    other_session = IDS.uuid()
    other_desk.create_session({"session_id": other_session, "title": "다른 데스크"})
    foreign = other_desk.submit({"session_id": other_session, "request_id": IDS.uuid(), "intent": "consult",
                                 "text": "남의 메시지"})
    with other_desk.store.transaction() as tx:
        bus.publish(tx.get("outbox", api.message_id_of(foreign["request"]["id"]))["message"])
    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, desk, executor, bus)
    step = w.step(desk_runner)
    out["test_a_foreign_stream_entry_fails_this_turn_and_is_left_pending"] = {
        "step": plain(step), "calls": plain(executor.calls), "acked": bus.acked,
        "pending": {agent: [entry_id for entry_id, _ in entries] for agent, entries in bus.streams.items()},
        "row": plain(desk.request(accepted["request"]["id"])), "receipt": plain(desk.receipt(accepted["request"]["id"]))}

    # ---- test_a_missing_stream_entry_fails_the_turn_without_execution
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)

    class EmptyBus(d.FakeBus):
        def receive(self, agent, consumer, idle_ms=60000):
            return None

    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, desk, executor, EmptyBus())
    step = w.step(desk_runner)
    out["test_a_missing_stream_entry_fails_the_turn_without_execution"] = {
        "step": plain(step), "calls": plain(executor.calls), "row": plain(desk.request(accepted["request"]["id"]))}

    # ---- test_execution_guard_refuses_a_foreign_queued_task_before_any_entry
    svc, desk, session_id = w.opened()
    w.submit(desk, session_id)
    desk_runner, bus = w.runner(svc, desk, d.FakeExecutor(svc))
    row = desk.claim_next()
    flushed = desk_runner._flush(row["correlation_id"])
    delivered = desk_runner._deliver(row)
    workflow = api.Workflow(svc.store, svc.org)
    out["test_execution_guard_refuses_a_foreign_queued_task_before_any_entry"] = {
        "flushed": plain(flushed), "delivered": delivered, "acked": bus.acked, "task_after_deliver": rows(svc.store, "tasks"),
        "guard": refused(svc.store, workflow.claim, api.LEAD, "other-owner",
                         expected={"id": "desk-" + IDS.uuid(), "correlation_id": row["correlation_id"],
                                   "statuses": {"queued"}}),
        "guard_refusal_is_claim_guard": refused(svc.store, workflow.claim, api.LEAD, "other-owner",
                                                expected={"id": "desk-" + IDS.uuid(),
                                                          "correlation_id": row["correlation_id"],
                                                          "statuses": {"queued"}})["refused"] == api.ClaimGuardRefused.__name__}
    return out


# ---- restart and recovery ----------------------------------------------------------------------------------------------
def g4_recovery(api, w) -> dict:
    out = {}
    d = w.d

    # ---- test_a_terminal_write_failure_leaves_the_turn_dispatching_and_stops_the_process
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    request_id = accepted["request"]["id"]
    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, d.UnavailableFinalize(svc, REVISION), executor)
    step = w.step(desk_runner)
    out["test_a_terminal_write_failure_leaves_the_turn_dispatching_and_stops_the_process"] = {
        "step": plain(step), "stopping": desk_runner.stopping, "calls": len(executor.calls),
        "row": plain(desk.request(request_id)), "receipt": plain(desk.receipt(request_id)),
        "failure": plain(desk_runner.failure)}

    # ---- test_restart_finalizes_a_receipted_turn_without_another_provider_call
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    request_id = accepted["request"]["id"]
    interrupted, bus = w.runner(svc, d.UnavailableFinalize(svc, REVISION), d.FakeExecutor(svc))
    w.step(interrupted)  # the turn ran and was receipted; the process died before its final status
    restarted_executor = d.FakeExecutor(svc)
    restarted, _ = w.runner(svc, api.FrontDesk(svc, REVISION), restarted_executor, bus)
    recovered = restarted.recover()
    out["test_restart_finalizes_a_receipted_turn_without_another_provider_call"] = {
        "recovered": plain(recovered), "calls": plain(restarted_executor.calls), "row": plain(desk.request(request_id)),
        "events": rows(svc.store, "desk_events")}

    # ---- test_a_succeeded_task_without_a_receipt_stays_unknown_instead_of_answered
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    request_id = accepted["request"]["id"]
    executor = d.FakeExecutor(svc)
    desk_runner, bus = w.runner(svc, desk, executor)
    row = desk.claim_next()
    desk_runner._flush(row["correlation_id"])
    desk_runner._deliver(row)
    executor.execute_one(api.LEAD, expected={"id": row["message_id"], "correlation_id": row["correlation_id"],
                                             "statuses": {"queued"}})
    receipt_before = desk.receipt(request_id)
    restarted_executor = d.FakeExecutor(svc)
    restarted, _ = w.runner(svc, api.FrontDesk(svc, REVISION), restarted_executor, bus)
    recovered = restarted.recover()
    out["test_a_succeeded_task_without_a_receipt_stays_unknown_instead_of_answered"] = {
        "receipt_before": receipt_before, "recovered": plain(recovered), "calls": plain(restarted_executor.calls),
        "stored": plain(desk.request(request_id)), "tasks": rows(svc.store, "tasks")}

    # ---- test_recovery_refuses_a_receipt_that_binds_another_turn
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    request_id = accepted["request"]["id"]
    interrupted, bus = w.runner(svc, d.UnavailableFinalize(svc, REVISION), d.FakeExecutor(svc))
    w.step(interrupted)
    with svc.store.transaction() as tx:
        receipt = tx.get("desk_receipts", request_id)
        tx.put("desk_receipts", request_id, {**receipt, "task_id": "desk-" + IDS.uuid()})
    restarted, _ = w.runner(svc, api.FrontDesk(svc, REVISION), d.FakeExecutor(svc), bus)
    out["test_recovery_refuses_a_receipt_that_binds_another_turn"] = {
        "recovered": plain(restarted.recover()), "row": plain(desk.request(request_id))}

    # ---- test_restart_without_a_matching_result_keeps_the_uncertainty
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    desk.claim_next()
    executor = d.FakeExecutor(svc)
    restarted, _ = w.runner(svc, api.FrontDesk(svc, REVISION), executor)
    recovered = restarted.recover()
    out["test_restart_without_a_matching_result_keeps_the_uncertainty"] = {
        "recovered": plain(recovered), "calls": plain(executor.calls), "row": plain(desk.request(accepted["request"]["id"])),
        "claim_after": desk.claim_next()}

    # ---- test_queued_work_survives_a_restart_and_runs_afterwards
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, api.FrontDesk(svc, REVISION), executor)
    summary = desk_runner.run(once=True)
    out["test_queued_work_survives_a_restart_and_runs_afterwards"] = {
        "summary": plain(summary), "row": plain(desk.request(accepted["request"]["id"])),
        "again": plain(desk_runner.run(once=True))}

    # ---- test_a_dispatch_exception_ends_the_turn_in_explicit_uncertainty
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)

    class BrokenBus(d.FakeBus):
        def receive(self, agent, consumer, idle_ms=60000):
            raise RuntimeError("injected transport failure")

    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, desk, executor, BrokenBus())
    step = w.step(desk_runner)
    out["test_a_dispatch_exception_ends_the_turn_in_explicit_uncertainty"] = {
        "step": plain(step), "calls": plain(executor.calls), "claim_after": desk.claim_next(),
        "row": plain(desk.request(accepted["request"]["id"]))}

    # ---- test_observations_are_collected_after_recovery_and_after_each_turn
    svc, desk, session_id = w.opened()
    w.submit(desk, session_id)
    collector = d.FakeCollector()
    desk_runner, _ = w.runner(svc, desk, d.FakeExecutor(svc), collector=collector)
    summary = desk_runner.run(once=True)
    out["test_observations_are_collected_after_recovery_and_after_each_turn"] = {
        "collector_calls": collector.calls, "summary": plain(summary)}

    # ---- test_a_collection_failure_is_reported_and_never_hides_the_turn
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    collector = d.FakeCollector(error=OSError("injected spool failure"))
    desk_runner, _ = w.runner(svc, desk, d.FakeExecutor(svc), collector=collector)
    summary = desk_runner.run(once=True)
    out["test_a_collection_failure_is_reported_and_never_hides_the_turn"] = {
        "summary": plain(summary), "row": plain(desk.request(accepted["request"]["id"]))}

    # ---- test_the_loop_summary_stays_bounded_and_reports_what_it_omitted
    svc, desk, session_id = w.opened()
    desk_runner, _ = w.runner(svc, desk, d.FakeExecutor(svc))
    summary = {"turns": [], "turn_count": 0, "omitted_turns": 0, "statuses": {}}
    total = api.SUMMARY_TURNS + 10
    for index in range(total):
        desk_runner._record(summary, {"action": "turn", "request_id": "r%d" % index,
                                      "status": "answered" if index % 2 else "failed"})
    out["test_the_loop_summary_stays_bounded_and_reports_what_it_omitted"] = {
        "summary": plain(summary), "limit": api.SUMMARY_TURNS, "total": total}

    # ---- test_stop_prevents_a_new_claim
    svc, desk, session_id = w.opened()
    w.submit(desk, session_id)
    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, desk, executor)
    desk_runner.stop()
    step = desk_runner.step()
    out["test_stop_prevents_a_new_claim"] = {
        "step": plain(step), "calls": plain(executor.calls), "stopping": desk_runner.stopping,
        "requests": rows(svc.store, "desk_requests")}
    return out


# ---- LABELLED additions: the branches the M7 tests do not reach ------------------------------------------------------------
def g5_labelled(api, w) -> dict:
    out = {}
    d = w.d

    # `_classify_result`: every branch
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    row = desk.request(accepted["request"]["id"])
    desk_runner, _ = w.runner(svc, desk, d.FakeExecutor(svc))
    request_row = {**row, "intent": "request"}
    good = {"id": row["message_id"], "status": "succeeded", "result": dict(ANSWER)}
    results = {
        "not_a_dict": None, "string": "text", "failed": {"id": row["message_id"], "status": "failed"},
        "status_with_unsafe_text": {"id": row["message_id"], "status": "bad status!"},
        "status_not_text": {"id": row["message_id"], "status": 7},
        "result_unbound": {**good, "id": "desk-other"},
        "answer_invalid": {**good, "result": {"answer": ""}},
        "answer_not_a_dict": {**good, "result": "plain"},
        "succeeded": good,
        "execution_ref_not_text": {**good, "result": {**ANSWER, "execution_ref": 7}},
        "execution_ref_absent": {**good, "result": {key: value for key, value in ANSWER.items() if key != "execution_ref"}}}
    out["classify_result"] = {name: {"consult": plain(desk_runner._classify_result(row, result)),
                                     "request": plain(desk_runner._classify_result(request_row, result))}
                              for name, result in results.items()}

    # `_bound_execution`: pins the deadline and retry budget once, only on this turn's own queued task
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    desk_runner, bus = w.runner(svc, desk, d.FakeExecutor(svc))
    claimed = desk.claim_next()
    desk_runner._flush(claimed["correlation_id"])
    desk_runner._deliver(claimed)
    case = {"after_deliver": rows(svc.store, "tasks")}
    desk_runner._bound_execution(claimed)
    case["again"] = rows(svc.store, "tasks") == case["after_deliver"]
    with svc.store.transaction() as tx:
        task = tx.get("tasks", claimed["message_id"])
        task.update(execution_deadline="2030-01-01T00:00:00+00:00", retry_budget={"max_attempts": 5})
        tx.put("tasks", task["id"], task)
    desk_runner._bound_execution(claimed)
    case["preset_kept"] = rows(svc.store, "tasks")
    with svc.store.transaction() as tx:
        task = tx.get("tasks", claimed["message_id"])
        task.update(execution_deadline=None, retry_budget=None, attempt=1)
        tx.put("tasks", task["id"], task)
    desk_runner._bound_execution(claimed)
    case["attempted_task_gets_only_a_deadline"] = rows(svc.store, "tasks")
    with svc.store.transaction() as tx:
        task = tx.get("tasks", claimed["message_id"])
        task.update(execution_deadline=None, retry_budget=None, attempt=0, status="running")
        tx.put("tasks", task["id"], task)
    before = store_digest(svc.store)
    desk_runner._bound_execution(claimed)
    case["not_queued_untouched"] = store_digest(svc.store) == before
    with svc.store.transaction() as tx:
        task = tx.get("tasks", claimed["message_id"])
        task.update(status="queued", message={**task["message"], "correlation_id": "frontdesk:other"})
        tx.put("tasks", task["id"], task)
    before = store_digest(svc.store)
    desk_runner._bound_execution(claimed)
    case["foreign_correlation_untouched"] = store_digest(svc.store) == before
    before = store_digest(svc.store)
    desk_runner._bound_execution({**claimed, "message_id": "desk-missing"})
    case["missing_task_untouched"] = store_digest(svc.store) == before
    out["bound_execution"] = case

    # `recover` and `_recovered`: a stored success whose publication is incomplete / whose result is not the success state
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    request_id = accepted["request"]["id"]
    interrupted, bus = w.runner(svc, d.UnavailableFinalize(svc, REVISION), d.FakeExecutor(svc))
    w.step(interrupted)

    class DownBus(d.FakeBus):
        def publish(self, message):
            raise api.MessageDeliveryError("injected publish failure")

    restarted, _ = w.runner(svc, api.FrontDesk(svc, REVISION), d.FakeExecutor(svc), DownBus())
    with svc.store.transaction() as tx:  # LABELLED injected fault: the stored result's delivery receipt and sent flag are lost
        for outbox_row in tx.scan("outbox"):
            if outbox_row["message"]["type"] == "task.result":
                identity = outbox_row["message"]["message_id"]
                delivery = tx.get("outbox_delivery", identity)
                tx.put("outbox", identity, {**outbox_row, "sent": False})
                tx.put("outbox_delivery", identity, {key: value for key, value in delivery.items()
                                                     if key != "delivered_entry_id"})
    with svc.store.transaction() as tx:
        task = tx.get("tasks", api.message_id_of(request_id))
    out["recover_publication_incomplete"] = {
        "task_status": task["status"], "recovered": plain(restarted.recover()), "row": plain(desk.request(request_id)),
        "outbox": rows(svc.store, "outbox")}

    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id, intent="request")
    request_id = accepted["request"]["id"]
    interrupted, bus = w.runner(svc, d.UnavailableFinalize(svc, REVISION), d.FakeExecutor(svc))
    w.step(interrupted)
    with svc.store.transaction() as tx:  # the stored success is a malformed answer: `_classify_result` fails it
        task = tx.get("tasks", api.message_id_of(request_id))
        task["result"] = {"answer": ""}
        tx.put("tasks", task["id"], task)
    restarted, _ = w.runner(svc, api.FrontDesk(svc, REVISION), d.FakeExecutor(svc), bus)
    out["recover_unclassifiable_success"] = {"recovered": plain(restarted.recover()), "row": plain(desk.request(request_id))}

    # a turn whose publication of the assignment is incomplete: nothing external ran
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, desk, executor, DownBus())
    step = w.step(desk_runner)
    out["turn_with_the_assignment_unpublished"] = {
        "step": plain(step), "calls": plain(executor.calls), "row": plain(desk.request(accepted["request"]["id"])),
        "outbox": rows(svc.store, "outbox")}

    # a turn whose result publication is incomplete: a success is held for reconciliation
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)

    class ResultDownBus(d.FakeBus):
        def publish(self, message):
            if message["who"]["recipient"] != api.LEAD:
                raise api.MessageDeliveryError("injected publish failure")
            return super().publish(message)

    executor = d.FakeExecutor(svc)
    desk_runner, _ = w.runner(svc, desk, executor, ResultDownBus())
    step = w.step(desk_runner)
    out["turn_with_the_result_unpublished"] = {
        "step": plain(step), "row": plain(desk.request(accepted["request"]["id"])),
        "receipt": plain(desk.receipt(accepted["request"]["id"])), "outbox": rows(svc.store, "outbox")}

    # a runner without a bus or a workflow: nothing is delivered, the executor finds no task
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    executor = d.FakeExecutor(svc)
    bare = api.DeskRunner(svc, desk, executor)
    step = w.step(bare)
    out["runner_without_a_bus"] = {
        "step": plain(step), "calls": plain(executor.calls), "row": plain(desk.request(accepted["request"]["id"])),
        "receipt": plain(desk.receipt(accepted["request"]["id"])), "flush": bare._flush("frontdesk:x"),
        "collect": bare._collect()}

    # the claim fails: the process stops and reports only the exception type
    svc, desk, session_id = w.opened()
    w.submit(desk, session_id)
    desk_runner, _ = w.runner(svc, d.UnavailableClaim(svc, REVISION), d.FakeExecutor(svc))
    step = w.step(desk_runner)
    out["claim_failure_stops_the_process"] = {
        "step": plain(step), "stopping": desk_runner.stopping, "failure": plain(desk_runner.failure),
        "summary": plain(desk_runner.run(once=True))}

    # `run` reports a storage stop as the run's failure, and keeps the first failure
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    desk_runner, _ = w.runner(svc, d.UnavailableFinalize(svc, REVISION), d.FakeExecutor(svc))
    summary = desk_runner.run(once=True)
    out["run_reports_a_storage_stop"] = {
        "summary": plain(summary), "row": plain(desk.request(accepted["request"]["id"])),
        "second_failure_keeps_the_first": plain(desk_runner._unavailable("other", ValueError("later"))),
        "failure_after": plain(desk_runner.failure)}

    # an idle continuous desk waits `interval` seconds, then a stop ends the loop
    svc, desk, session_id = w.opened()
    desk_runner, _ = w.runner(svc, desk, d.FakeExecutor(svc))
    waits = []
    desk_runner.sleep = lambda seconds: (waits.append(seconds), desk_runner.stop())
    summary = desk_runner.run()
    out["idle_wait_then_stop"] = {"waits": waits, "summary": plain(summary), "interval": desk_runner.interval}

    # the FrontDesk read and write surface not reached above
    svc, desk, session_id = w.opened()
    accepted = w.submit(desk, session_id)
    request_id = accepted["request"]["id"]
    case = {"unknown_request": desk.request(IDS.uuid()), "unknown_receipt": desk.receipt(request_id),
            "dispatching_before": plain(desk.dispatching()),
            "finalize_unknown": refused(svc.store, desk.finalize, IDS.uuid(), "t", status="answered"),
            "finalize_not_dispatching": refused(svc.store, desk.finalize, request_id, "t", status="answered"),
            "bad_revision": refused(svc.store, api.FrontDesk, svc, "not-a-revision"),
            "correlation": api.correlation_of(request_id), "message_id": api.message_id_of(request_id)}
    claimed = desk.claim_next()
    case["dispatching_after"] = plain(desk.dispatching())
    case["finalize_not_terminal"] = refused(svc.store, desk.finalize, request_id, claimed["owner_token"], status="queued")
    case["finalize_empty_token"] = refused(svc.store, desk.finalize, request_id, "", status="answered")
    finalized = desk.finalize(request_id, claimed["owner_token"], status="failed", reason_code="bad code!", answer="text",
                              task_id=7, execution_ref=9)
    case["finalize_sanitizes"] = plain(finalized)
    receipt_row = {**finalized, "task_id": None}
    first = desk.record_receipt(receipt_row, None, [{"id": "s1", "kind": "task", "settled": True}], True)
    api.advance(1)
    second = desk.record_receipt(receipt_row, "other", [{"id": "s2", "kind": "task", "settled": False}], False)
    case["receipt_first"], case["receipt_never_rewritten"] = plain(first), plain(second) == plain(first)
    case["events"] = plain(desk.events())
    out["frontdesk_surface"] = case
    return out


GROUPS = (("g1_intake", g1_intake), ("g2_evidence", g2_evidence), ("g3_turns", g3_turns), ("g4_recovery", g4_recovery),
          ("g5_labelled", g5_labelled))


def run(api) -> dict:
    api.reset()
    world = World(api)
    result, counts = {}, {}
    for name, group in GROUPS:
        result[name] = group(api, world)
        counts[name] = len(result[name])
    result["unreachable"] = {test: UNREACHABLE[kind] for test, kind in UNREACHABLE_TESTS}
    result["cases_per_group"] = counts
    result["unreachable_count"] = len(UNREACHABLE_TESTS)
    return result
