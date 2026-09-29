"""Execution ports: what one invocation needs from other contexts, declared by execution (§2.4, §2.5).

Layer: ports
Context: execution
Owns: OWNED_BUCKETS of the execution context; the consumer-owned Protocols RunTask depends on
Does not own: their implementations (coordination implements TaskLedger in S5, research/evidence
    implement ResearchAdmission in S8; composition wires them in S10)
Entry points: OWNED_BUCKETS, TaskLedger, ResearchAdmission, ProviderRuntime
Contracts: INV-INVOCATION-001, INV-WORKER-SESSION-001, INV-EXECUTION-IDENTITY-001

Protocols are structural: an implementation never imports this module (§2.4).
"""

from __future__ import annotations

from typing import Protocol

from codex_harness.storage.ports import Transaction

OWNED_BUCKETS = ("invocation_reservations", "worker_sessions")


class TaskLedger(Protocol):
    """Lease ownership of one running execution (coordination's TaskOwnership, S5)."""

    def owned(self, tx: Transaction, lease: dict) -> dict:
        """The current row when `lease` still owns it (status, generation, attempt, owner, durable
        fence and deadline checked in `tx`); raises ContractError("Stale or expired task execution")."""
        ...

    def heartbeat(self, lease: dict) -> dict: ...


class ResearchAdmission(Protocol):
    """RF-RT (addendum A1 v2), S4 part: RunTask consults this before a design/implementation
    dispatch. S8 owns the package store; S5 persists the disposition; S10 wires it."""

    def admit(self, tx: Transaction, lease: dict, action: str) -> dict:
        """{"disposition": "admit" | "exempt" | "research" | "blocked", "reason": str}."""
        ...


class ProviderRuntime(Protocol):
    """One opened provider transport (Codex App Server or Claude Code CLI, host or container)."""

    def __enter__(self) -> "ProviderRuntime": ...

    def __exit__(self, *exc) -> bool | None: ...

    def run(self, prompt: str, cwd: str, schema: dict, timeout: float, **kwargs) -> dict: ...

