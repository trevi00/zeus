"""S5 declared boundaries the coordination goldens do not reach (DESIGN-s5 §M/§O/§L/§Op; CE-9: an absent required
collaborator refuses before any effect, never a silent skip).

- A MessageHandler without the terminal-operation park refuses at construction.
- A global outbox batch without observation's health owner operation refuses before any unit; a scoped batch never
  needs it.
- A LocalCycle incident report without research's incident port refuses, and the entry is not ACKed.
- An Operation without evidence records refuses before its claim writes anything, and a designed manifest without
  the design gate refuses inside the claim unit, so nothing is written.
"""

from __future__ import annotations

import pytest

from codex_harness.coordination.application.local_cycle import LocalCycle
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.coordination.application.operation import Operation
from codex_harness.coordination.application.outbox_relay import OutboxFlusher, relay
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.coordination.domain.operation import validate_manifest
from codex_harness.evidence.application.inspections import EvidenceRecords
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.research.application.audit_gate import require_adoption
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.adapters.provider_policy import packaged_policy
from codex_harness.storage.adapters.memory_store import MemoryStore

ORG = packaged_organization()
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": "a" * 40, "bytes": 3}
IDENTITY = {"repository": "r", "runtime": "d", "runtime_policy": "p",
            "provider": {"policy_digest": "x", "config_digest": "y"}}


def manifest():
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": "op-1", "base_revision": "a" * 40,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "rationale": "r"},
        "plan": {"objective": "o", "acceptance_criteria": ["ok"], "allowed_paths": ["docs/x.md"]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}}, packaged_policy())


def records(store):
    with store.transaction() as tx:
        return tx.records()


def workflow(store, park=None):
    return Workflow(store, ORG, ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                    adoption=require_adoption, park_terminal=park)


def test_a_message_handler_without_the_park_refuses_at_construction():
    with pytest.raises(ContractError, match="Terminal-operation parking is not wired"):
        MessageHandler(workflow(MemoryStore()))


def test_a_global_relay_batch_needs_the_health_owner_operation_and_a_scoped_batch_does_not():
    store = MemoryStore()
    message = envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": {"objective": "x"}}, "c1")
    with store.transaction() as tx:
        tx.put("outbox", message["message_id"], {"message": message, "sent": False})
    before = records(store)

    class Bus:
        published = []

        @staticmethod
        def validate(m):
            return m

        def publish(self, m):
            self.published.append(m["message_id"])
            return "entry-1"

    with pytest.raises(ContractError, match="Outbox health recording is not wired"):
        relay(store, ORG, Bus(), 100, None, None)
    assert records(store) == before and Bus.published == []
    out = OutboxFlusher(store, ORG).flush(Bus(), correlation_id="c1")
    assert out["published"] == 1 and out["complete"] is True


def test_a_cycle_incident_report_without_the_incident_port_refuses_and_is_not_acked():
    store, acks = MemoryStore(), []
    report = envelope("incident.report", "worker:implementation", "lead:improvement", "report",
                      {"occurrence_id": "o1", "root_cause": "r", "scope": "s", "evidence_refs": []}, "corr")

    class Bus:
        served = False

        def receive(self, agent, consumer):
            if agent == "lead:improvement" and not self.served:
                self.served = True
                return "1-0", {"body": report}
            return None

        @staticmethod
        def decode(fields):
            return fields["body"]

        def ack(self, agent, entry_id):
            acks.append(entry_id)

        def dead_letter(self, agent, entry_id, fields, reason):
            acks.append(("dead", entry_id))

    cycle = LocalCycle(store, ORG, flusher=OutboxFlusher(store, ORG), bus=Bus(), workflow=None)
    cycle.start("cycle-1", "corr", 2)
    with pytest.raises(ContractError, match="Incident recording is not wired"):
        cycle.step("cycle-1")
    assert acks == []


def test_an_operation_without_evidence_records_refuses_before_its_claim_writes():
    store = MemoryStore()
    op = Operation(store, ORG, flusher=OutboxFlusher(store, ORG), executor=object(), budget=object())
    with pytest.raises(ContractError, match="Evidence records are not wired"):
        op.run(manifest(), IDENTITY, GOAL)
    assert records(store) == []


def test_a_designed_manifest_without_the_design_gate_refuses_inside_the_claim_unit():
    store = MemoryStore()
    op = Operation(store, ORG, flusher=OutboxFlusher(store, ORG), evidence_records=EvidenceRecords())
    designed = {**manifest(), "design": {"session_id": "s-1", "packet_digest": "c" * 64}}
    with pytest.raises(ContractError, match="Design gate is not wired"):
        op.claim(designed, IDENTITY, GOAL)
    assert records(store) == []
