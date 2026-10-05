"""S11 XC-3 (TQ-XCUT-PLAN B4 redesign): `operations.task_spec_bound {task_id, spec_digest}`.

Expected results come from the owner rule in the spec: one event per task row created from a message that binds exactly
one Zeus ticket, its `spec_digest` the binding's `content_hash`; none for no binding, conflicting bindings or a
duplicate delivery; an observer that raises changes nothing. Every test drives `MessageHandler.handle` / `Workflow.submit`
and observes the spool, the store and the response.
"""

from __future__ import annotations

from threading import Thread
from types import SimpleNamespace

import pytest

from codex_harness.composition import cli, cli_cycle
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.intake.application.tickets import Tickets, TicketSuperseded
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.application.observations import Observer
from codex_harness.observation.domain.observation import REGISTRY, new_process_run_id
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

EVENT = "operations.task_spec_bound"


class MemoryDirectory:
    def pending_terminations(self, task_id=None):
        return []

    def read_health(self):
        return None


def real_observer():
    return CatalogCheckingObserver(Observer(None, MemorySpool(new_process_run_id()), component="xc3-test",
                                            directory=MemoryDirectory(), clock=lambda: "2026-10-05T00:00:00+00:00"))


def bound_events(observer):
    return [r for r in observer.spool.records() if r["event_type"] == EVENT]


def world(observer):
    service = SimpleNamespace(store=MemoryStore(), org=packaged_organization())
    return service, cli.messages(service, observer)


def content(title):
    return {"title": title, "problem": "p", "impact": "i", "rollback": "r", "evidence_refs": ["e"], "scope": ["s"],
            "acceptance_criteria": ["a"], "verification": ["v"]}


def ticket(service, title):
    row = Tickets(service.store, service.org).create(content(title))
    return {"id": row["id"], "revision": row["revision"], "content_hash": row["content_hash"]}


def assign(details, recipient="worker:implementation"):
    sender = packaged_organization().actor(recipient).parent
    return envelope("task.assign", sender, recipient, "implement", details, "xc3")


def task_row(service, task_id):
    with service.store.transaction() as tx:
        return tx.get("tasks", task_id)


def test_a_task_binding_one_ticket_emits_one_event_with_the_binding_content_hash():
    observer = real_observer()
    service, handler = world(observer)
    binding = ticket(service, "one")
    message = assign({"objective": "x", "zeus_ticket": binding})
    created = handler.handle(message)
    events = bound_events(observer)
    assert [e["attributes"] for e in events] == [{"task_id": message["message_id"], "spec_digest": binding["content_hash"]}]
    assert created["id"] == message["message_id"]


def test_a_binding_nested_in_the_details_is_found_as_the_ticket_binding_finds_it():
    observer = real_observer()
    service, handler = world(observer)
    binding = ticket(service, "nested")
    message = assign({"objective": "x", "plan": {"origin": {"zeus_ticket": binding}}})
    handler.handle(message)
    assert [e["attributes"]["spec_digest"] for e in bound_events(observer)] == [binding["content_hash"]]


def test_two_concurrent_tasks_with_different_tickets_emit_two_events_with_their_own_digests():
    observer = real_observer()
    service, handler = world(observer)
    first, second = ticket(service, "h1"), ticket(service, "h2")
    assert first["content_hash"] != second["content_hash"]
    messages = [assign({"objective": "a", "zeus_ticket": first}), assign({"objective": "b", "zeus_ticket": second})]
    threads = [Thread(target=handler.handle, args=(m,)) for m in messages]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    got = sorted((e["attributes"]["task_id"], e["attributes"]["spec_digest"]) for e in bound_events(observer))
    assert got == sorted([(messages[0]["message_id"], first["content_hash"]),
                          (messages[1]["message_id"], second["content_hash"])])


def test_a_task_without_a_binding_emits_nothing_but_is_created():
    observer = real_observer()
    service, handler = world(observer)
    message = assign({"objective": "no ticket"})
    handler.handle(message)
    assert task_row(service, message["message_id"]) is not None
    assert bound_events(observer) == []


def test_conflicting_bindings_create_no_task_and_emit_nothing():
    observer = real_observer()
    service, handler = world(observer)
    message = assign({"objective": "x", "zeus_ticket": ticket(service, "a"),
                      "plan": {"origin": {"zeus_ticket": ticket(service, "b")}}})
    with pytest.raises(ContractError):
        handler.handle(message)
    assert task_row(service, message["message_id"]) is None
    assert bound_events(observer) == []


def test_a_superseded_ticket_creates_no_task_and_emits_nothing():
    observer = real_observer()
    service, handler = world(observer)
    binding = ticket(service, "old")
    Tickets(service.store, service.org).update(binding["id"], 1, content("new"), "edit")
    message = assign({"objective": "x", "zeus_ticket": binding})
    with pytest.raises(TicketSuperseded):
        handler.handle(message)
    assert task_row(service, message["message_id"]) is None
    assert bound_events(observer) == []


def test_a_redelivered_message_creates_no_new_task_and_emits_no_second_event():
    observer = real_observer()
    service, handler = world(observer)
    message = assign({"objective": "x", "zeus_ticket": ticket(service, "dup")})
    first = handler.handle(message)
    second = handler.handle(message)
    assert second == first
    assert len(bound_events(observer)) == 1


def test_an_observer_that_raises_leaves_the_task_row_and_the_response_unchanged():
    class Failing:
        def emit(self, *args, **kwargs):
            raise RuntimeError("observer down")

    plain_service, plain = world(None)
    failing_service, failing = world(Failing())
    message_one = assign({"objective": "x", "zeus_ticket": ticket(plain_service, "same")})
    message_two = {**message_one}
    # the same message and ticket rows in both worlds: copy the ticket rows across
    with plain_service.store.transaction() as source, failing_service.store.transaction() as target:
        for bucket in ("tickets", "ticket_revisions"):
            for row in source.scan(bucket):
                target.put(bucket, row["id"] if bucket == "tickets" else f'{row["id"]}:{row["revision"]}', row)
    expected = plain.handle(message_one)
    got = failing.handle(message_two)
    stored = task_row(failing_service, message_one["message_id"])
    clock_free = lambda row: {k: v for k, v in row.items() if k != "created_at"}  # noqa: E731 - wall-clock stamp only
    assert clock_free(got) == clock_free(expected) and clock_free(stored) == clock_free(got)


def test_the_serve_handler_composition_threads_the_observer_to_the_workflow():
    observer = real_observer()
    service = SimpleNamespace(store=MemoryStore(), org=packaged_organization())
    handler = cli_cycle.serve_handler(service, observer)
    binding = ticket(service, "serve")
    message = assign({"objective": "x", "zeus_ticket": binding})
    handler.handle(message)
    assert [e["attributes"]["spec_digest"] for e in bound_events(observer)] == [binding["content_hash"]]
    assert isinstance(handler, MessageHandler)


def test_the_event_is_catalogued_with_exactly_its_two_attributes():
    assert set(REGISTRY[EVENT]) == {"task_id", "spec_digest"}
