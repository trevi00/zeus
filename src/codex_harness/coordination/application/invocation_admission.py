"""InvocationBreaker: the breaker admission RunTask calls per provider invocation (DESIGN-run-task D8).

Layer: application
Context: coordination
Owns: InvocationBreaker, the implementation of execution.ports InvocationAdmission over the moved Breaker and
    its key/verdict functions. It delegates unchanged; M7 `Executor._run` called `self.breaker.admit/report` and
    `breaker_key/result_of/result_of_exception` directly
Does not own: the breaker rules (Breaker); the provider call (execution)
Entry points: InvocationBreaker
Contracts: INV-RECURRENCE-001
"""

from __future__ import annotations

from codex_harness.coordination.application.breaker import (
    Breaker,
    breaker_key,
    result_of,
    result_of_exception,
)


class InvocationBreaker:
    """A stateless facade over one Breaker (one instance per composition)."""

    def __init__(self, breaker: Breaker):
        self.breaker = breaker

    def admit(self, key: str, lease: dict, now=None) -> dict:
        return self.breaker.admit(key, lease, now)

    def report(self, token: dict, result: str, now=None) -> dict:
        return self.breaker.report(token, result, now)

    def key(self, provider: str, scope: str) -> str:
        return breaker_key(provider, scope)

    def verdict(self, result) -> str:
        return result_of(result)

    def verdict_of_exception(self, error) -> str:
        return result_of_exception(error)
