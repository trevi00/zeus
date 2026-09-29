"""The packaged organization graph and message authorization.

Layer: domain
Context: routing
Owns: Agent, Organization (hierarchy validation, actor lookup, `authorize`), conductor_self_arbitration
Does not own: message delivery or deduplication (coordination), the packaged file (routing.adapters.organization_source)
Entry points: Organization.validate, Organization.actor, Organization.authorize, conductor_self_arbitration
Contracts: INV-COUNCIL-001, INV-MESSAGE-001

Moved from SOURCE M7 `domain/model.py`; every rule and refusal text is unchanged. Authority comes only
from the reporting edges of the packaged graph: role names grant nothing beyond them.
"""

from __future__ import annotations

from dataclasses import dataclass

from codex_harness.kernel.errors import require


@dataclass(frozen=True)
class Agent:
    id: str
    role: str
    parent: str | None
    team: str


@dataclass
class Organization:
    """The validated agent graph of one process; immutable in use (built once by composition)."""

    agents: dict[str, Agent]

    def validate(self) -> None:
        roots = [a for a in self.agents.values() if a.role == "conductor"]
        require(len(roots) == 1, "Exactly one conductor is required")
        for key, agent in self.agents.items():
            require(key == agent.id, "Agent key and identity differ")
            require(agent.role in {"conductor", "lead", "worker"}, "Unknown role")
            if agent.role == "conductor":
                require(agent.parent is None, "Conductor cannot have a parent")
            else:
                parent = self.agents.get(agent.parent or "")
                expected = "conductor" if agent.role == "lead" else "lead"
                require(parent is not None and parent.role == expected, "Invalid hierarchy")
                if agent.role == "worker":
                    require(parent.team == agent.team, "Worker must belong to parent's team")

    def actor(self, actor_id: str, role: str | None = None) -> Agent:
        require(actor_id in self.agents, "Unknown actor")
        actor = self.agents[actor_id]
        require(role is None or actor.role == role, "Actor lacks required role")
        return actor

    def authorize(self, message: dict) -> None:
        """Refuse (ContractError) a message whose sender/recipient pair is not a permitted edge."""
        sender = self.actor(message["who"]["sender"])
        recipient = self.actor(message["who"]["recipient"])
        self.actor(message["who"]["owner"])
        kind = message["type"]
        if sender.role == "conductor" and conductor_self_arbitration(message):
            return  # INV-COUNCIL-001: the only self-addressed shape; every other rule below is unchanged
        if kind == "task.assign":
            require(recipient.parent == sender.id, "Assignment must follow a direct reporting edge")
        elif kind == 'execution.notice':
            require(recipient.id == (sender.parent or sender.id), 'Execution notice must follow the reporting edge')
            require(message['what']['action'] == 'observe_execution', 'Execution notice cannot assign work')
        elif kind == "review.result":
            require(sender.role in {"lead", "conductor"}, "Worker cannot approve")
        elif kind in {"incident.report", "task.result", "hook.required"}:
            require(sender.parent == recipient.id, "Report must go to the direct parent")


def conductor_self_arbitration(message: dict) -> bool:
    """INV-COUNCIL-001: the one self-addressed message shape the organization admits: the conductor's
    own `dge_role` arbitration task (details.role == "conductor") and that task's `task.result`.
    General self-assignment, worker impersonation and every other type stay refused."""
    who, what = message.get("who") or {}, message.get("what") or {}
    if who.get("sender") != "conductor" or who.get("recipient") != "conductor" or what.get("action") != "dge_role":
        return False
    if message.get("type") == "task.assign":
        return isinstance(what.get("details"), dict) and what["details"].get("role") == "conductor"
    return message.get("type") == "task.result"
